"""Benchmark: calibra os limiares de paralelismo intra-tabela.

`_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA` (100_000) e
`_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA` (500_000_000)
(`extractors/comum/leitura_paralela_intra_tabela.py`) — benchmarks/spikes
anteriores provam ganho de 2.7-4x numa tabela de ~4M linhas (bem acima do
limiar), mas nunca mediram a fronteira em si.

Mesma metodologia de `test_calibracao_limiares_streaming.py`: dois perfis
(estreito isola o critério de linhas, largo isola o critério de bytes),
medindo tempo de parede dos dois lados de cada fronteira com o paralelismo
forçado ligado/desligado (`monkeypatch` do limiar em subprocesso isolado).
Mede só tempo, não RSS — o ganho esperado do paralelismo intra-tabela é
velocidade (paralelizar leitura fora do GIL via `connectorx`), não redução
de memória (ver Decisão 14 do `system_design_doc.md`).

Elegibilidade real (`AmostragemIntegral`, PK inteira de coluna única, não
particionada) é respeitada nas tabelas sintéticas abaixo.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/postgres/test_calibracao_limiares_paralelismo.py
"""

import subprocess
import sys
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.benchmark

# Perfil estreito: ~40 bytes/linha. Abaixo/acima do limiar de LINHAS
# (100_000); bytes totais nos dois casos ficam bem abaixo do limiar de
# bytes (500_000_000).
_N_ESTREITA_ABAIXO = 20_000
_N_ESTREITA_ACIMA = 120_000

# Perfil largo: linhas fixas em 100.000 (bem abaixo do limiar de LINHAS),
# variando o payload TEXT pra cruzar o limiar de BYTES (500_000_000) —
# ~4.200 bytes/linha (abaixo, ~420MB) vs. ~5.800 bytes/linha (acima, ~580MB).
_N_LARGA = 100_000
_BYTES_PAYLOAD_ABAIXO = 4_200
_BYTES_PAYLOAD_ACIMA = 5_800

_DDL_ESTREITA = """
    CREATE TABLE public.{nome} (
        id INTEGER PRIMARY KEY,
        categoria INTEGER NOT NULL,
        rotulo VARCHAR(20) NOT NULL
    );
    INSERT INTO public.{nome} (id, categoria, rotulo)
    SELECT g, g % 50, 'r' || (g % 1000)
    FROM generate_series(1, {n}) AS g;
    ANALYZE public.{nome};
"""

_DDL_LARGA = """
    CREATE TABLE public.{nome} (
        id INTEGER PRIMARY KEY,
        payload TEXT NOT NULL
    );
    INSERT INTO public.{nome} (id, payload)
    SELECT g, rpad('x', {tamanho_payload}, 'x')
    FROM generate_series(1, {n}) AS g;
    ANALYZE public.{nome};
"""


@pytest.fixture(scope="module")
def dsn_calibracao() -> Iterator[str]:
    """Sobe um Postgres descartável com as 4 tabelas de fronteira."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(
                    _DDL_ESTREITA.format(
                        nome="estreita_abaixo", n=_N_ESTREITA_ABAIXO
                    )
                )
                cursor.execute(
                    _DDL_ESTREITA.format(nome="estreita_acima", n=_N_ESTREITA_ACIMA)
                )
                cursor.execute(
                    _DDL_LARGA.format(
                        nome="larga_abaixo",
                        n=_N_LARGA,
                        tamanho_payload=_BYTES_PAYLOAD_ABAIXO,
                    )
                )
                cursor.execute(
                    _DDL_LARGA.format(
                        nome="larga_acima",
                        n=_N_LARGA,
                        tamanho_payload=_BYTES_PAYLOAD_ACIMA,
                    )
                )
        yield url


def _medir_em_subprocesso(dsn: str, tabela: str, forcar_paralelo: bool) -> float:
    """Roda extrair_tabela num subprocesso isolado, medindo tempo de parede.

    Args:
        dsn: string de conexão do Postgres já semeado.
        tabela: nome da tabela a extrair (schema `public`).
        forcar_paralelo: True força os limiares pra 0 (paralelismo sempre
            elegível); False força pra infinito (nunca elegível, cai no
            caminho sequencial via `connectorx` de conexão única).

    Returns:
        tempo_segundos.
    """
    limiar_linhas = 0 if forcar_paralelo else 10**12
    limiar_bytes = 0 if forcar_paralelo else 10**15
    codigo = f"""
import time

import ddf.infrastructure.adapters.outbounds.extractors.comum.leitura_paralela_intra_tabela \\
    as paralelismo
import ddf.infrastructure.adapters.outbounds.extractors.estrategias.tabela_inteira as m1
import ddf.infrastructure.adapters.outbounds.extractors.postgres.extrator_postgres as m2
import ddf.domain.model.common.configuracao_de_extracao as m3

TabelaInteira = m1.TabelaInteira
ExtratorPostgres = m2.ExtratorPostgres
ConfiguracaoDeExtracao = m3.ConfiguracaoDeExtracao

paralelismo._LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA = {limiar_linhas}
paralelismo._LIMIAR_BYTES_PARALELISMO_INTRA_TABELA = {limiar_bytes}

configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
extrator = ExtratorPostgres(dsn={dsn!r}, configuracao=configuracao, max_conexoes=8)

inicio = time.perf_counter()
resultado = extrator.extrair_tabela("public", {tabela!r})
tempo = time.perf_counter() - inicio

assert resultado.__class__.__name__ == "Sucesso", resultado
print(f"RESULTADO {{tempo}}")
"""
    processo = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    linha_resultado = next(
        linha for linha in processo.stdout.splitlines() if linha.startswith("RESULTADO")
    )
    _, tempo_str = linha_resultado.split()
    return float(tempo_str)


def _comparar(dsn: str, tabela: str, rotulo: str) -> None:
    """Mede on/off pra uma tabela e imprime o comparativo."""
    tempo_seq = _medir_em_subprocesso(dsn, tabela, forcar_paralelo=False)
    tempo_par = _medir_em_subprocesso(dsn, tabela, forcar_paralelo=True)

    print(f"\n--- {rotulo} ({tabela}) ---")
    print(f"sequencial: {tempo_seq:.3f}s | paralelo: {tempo_par:.3f}s")
    print(f"ganho de tempo: {tempo_seq / tempo_par:.2f}x")


def test_calibracao_paralelismo_perfil_estreito_cruza_limiar_de_linhas(
    dsn_calibracao: str,
) -> None:
    """Fronteira do limiar de LINHAS (100.000), perfil estreito (~40 bytes/linha)."""
    _comparar(
        dsn_calibracao, "estreita_abaixo", f"abaixo ({_N_ESTREITA_ABAIXO} linhas)"
    )
    _comparar(
        dsn_calibracao, "estreita_acima", f"acima ({_N_ESTREITA_ACIMA} linhas)"
    )


def test_calibracao_paralelismo_perfil_largo_cruza_limiar_de_bytes(
    dsn_calibracao: str,
) -> None:
    """Fronteira do limiar de BYTES (500.000.000), perfil largo (linhas fixas)."""
    _comparar(
        dsn_calibracao,
        "larga_abaixo",
        f"abaixo (~{_N_LARGA * _BYTES_PAYLOAD_ABAIXO / 1_000_000:.0f}MB)",
    )
    _comparar(
        dsn_calibracao,
        "larga_acima",
        f"acima (~{_N_LARGA * _BYTES_PAYLOAD_ACIMA / 1_000_000:.0f}MB)",
    )

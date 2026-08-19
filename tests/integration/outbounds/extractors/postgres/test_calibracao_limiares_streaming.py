"""Benchmark: calibra `_LIMIAR_LINHAS_STREAMING`/`_LIMIAR_BYTES_STREAMING`.

Os limiares em `extractors/comum/ler_amostra_em_lotes.py`
(`_LIMIAR_LINHAS_STREAMING=100_000`, `_LIMIAR_BYTES_STREAMING=100_000_000`)
seguiam "candidato, não calibrado" desde a issue #114 — os benchmarks
existentes (`test_extrator_postgres_benchmark_streaming.py`) provam que
streaming reduz RSS numa tabela bem acima do limiar (1M linhas), mas nunca
mediram a fronteira em si.

Este benchmark mede tempo e RSS de pico dos dois lados de cada fronteira,
em dois perfis de largura de linha:

- **estreita** (~40 bytes/linha, INTEGER + VARCHAR curto): isola o critério
  de linhas — o critério de bytes nunca se aproxima do limiar nos tamanhos
  usados aqui.
- **larga** (~2.400 bytes/linha, TEXT sujeito a TOAST): isola o critério de
  bytes — a contagem de linhas nunca se aproxima do limiar de 100.000 nos
  tamanhos usados aqui.

Para cada tabela (fixa), mede com streaming forçado ligado e desligado
(`monkeypatch` do limiar em subprocesso isolado, mesmo padrão do benchmark
da #114) — não "natural vs. forçado", mas as duas configurações possíveis,
deixando o resultado falar por si: se streaming ligado não reduz RSS de
forma material numa tabela already-acima do limiar, ou reduz de forma
material numa tabela already-abaixo, é sinal de que o limiar está no lugar
errado.

Ressalva de medição, mesma dos demais benchmarks do projeto: Docker local
tem I/O mais rápido que um Postgres gerenciado real — os tempos absolutos
são um PISO, não uma previsão de produção. RSS de pico é mais estável entre
ambientes que tempo de parede, mas ainda depende de `page cache`/SO.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/postgres/test_calibracao_limiares_streaming.py
"""

import subprocess
import sys
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.benchmark

# Perfil estreito: ~40 bytes/linha (2 INTEGER + VARCHAR(20) curto).
# Abaixo/acima do limiar de LINHAS (100_000); bytes totais nos dois casos
# ficam bem abaixo do limiar de bytes (100_000_000), então não interfere.
_N_ESTREITA_ABAIXO = 70_000
_N_ESTREITA_ACIMA = 130_000

# Perfil largo: linhas fixas em 40.000 (bem abaixo do limiar de LINHAS),
# variando o payload TEXT pra cruzar o limiar de BYTES (100_000_000) —
# ~2.000 bytes/linha (abaixo) vs. ~3.000 bytes/linha (acima).
_N_LARGA = 40_000
_BYTES_PAYLOAD_ABAIXO = 2_000
_BYTES_PAYLOAD_ACIMA = 3_000

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


def _medir_em_subprocesso(
    dsn: str, tabela: str, forcar_streaming: bool
) -> tuple[float, int]:
    """Roda extrair_tabela num subprocesso isolado, medindo tempo e RSS de pico.

    Args:
        dsn: string de conexão do Postgres já semeado.
        tabela: nome da tabela a extrair (schema `public`).
        forcar_streaming: True força o limiar de linhas pra 0 (streaming
            sempre ativo); False força o limiar pra infinito (streaming
            nunca ativo) — nunca depende do valor real hoje em produção.

    Returns:
        (tempo_segundos, pico_rss_kb).
    """
    limiar_linhas = 0 if forcar_streaming else 10**12
    limiar_bytes = 0 if forcar_streaming else 10**15
    codigo = f"""
import resource
import time

import ddf.infrastructure.adapters.outbounds.extractors.comum.ler_amostra_em_lotes as streaming
import ddf.infrastructure.adapters.outbounds.extractors.estrategias.tabela_inteira as m1
import ddf.infrastructure.adapters.outbounds.extractors.postgres.extrator_postgres as m2
import ddf.domain.model.common.configuracao_de_extracao as m3

TabelaInteira = m1.TabelaInteira
ExtratorPostgres = m2.ExtratorPostgres
ConfiguracaoDeExtracao = m3.ConfiguracaoDeExtracao

streaming._LIMIAR_LINHAS_STREAMING = {limiar_linhas}
streaming._LIMIAR_BYTES_STREAMING = {limiar_bytes}

configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
extrator = ExtratorPostgres(dsn={dsn!r}, configuracao=configuracao)

inicio = time.perf_counter()
resultado = extrator.extrair_tabela("public", {tabela!r})
tempo = time.perf_counter() - inicio

assert resultado.__class__.__name__ == "Sucesso", resultado
pico_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"RESULTADO {{tempo}} {{pico_rss_kb}}")
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
    _, tempo_str, pico_rss_str = linha_resultado.split()
    return float(tempo_str), int(pico_rss_str)


def _imprimir_linha(rotulo: str, tempo: float, rss_kb: int) -> None:
    """Formata uma linha da tabela de resultados do benchmark."""
    rss_mb = rss_kb / 1024
    print(f"{rotulo:<28} | {tempo:>8.3f} | {rss_mb:>10.1f}")


def _comparar(dsn: str, tabela: str, rotulo: str) -> None:
    """Mede on/off pra uma tabela e imprime o comparativo."""
    tempo_off, rss_off = _medir_em_subprocesso(dsn, tabela, forcar_streaming=False)
    tempo_on, rss_on = _medir_em_subprocesso(dsn, tabela, forcar_streaming=True)

    print(f"\n--- {rotulo} ({tabela}) ---")
    print("configuração                 |  tempo(s) | RSS pico(MB)")
    _imprimir_linha("streaming desligado", tempo_off, rss_off)
    _imprimir_linha("streaming ligado", tempo_on, rss_on)
    variacao_rss = (1 - rss_on / rss_off) * 100
    print(f"variação de RSS ao ligar: {variacao_rss:+.1f}%")


def test_calibracao_streaming_perfil_estreito_cruza_limiar_de_linhas(
    dsn_calibracao: str,
) -> None:
    """Fronteira do limiar de LINHAS (100.000), perfil estreito (~40 bytes/linha)."""
    _comparar(
        dsn_calibracao, "estreita_abaixo", f"abaixo ({_N_ESTREITA_ABAIXO} linhas)"
    )
    _comparar(
        dsn_calibracao, "estreita_acima", f"acima ({_N_ESTREITA_ACIMA} linhas)"
    )


def test_calibracao_streaming_perfil_largo_cruza_limiar_de_bytes(
    dsn_calibracao: str,
) -> None:
    """Fronteira do limiar de BYTES (100.000.000), perfil largo (linhas fixas)."""
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

"""Benchmark: RSS de pico e tempo — streaming e AmostragemPorFaixa (issue #114).

Reproduz a evidência real que motivou a issue: uma tabela outlier grande
(no caso real, `token_acesso`, 4.118.390 linhas/778MB) causava RSS de pico
~900MB isolado mesmo com `PercentualDeLinhas(10)` (default do wizard) —
porque `cursor.execute()` sem cursor nomeado materializa o resultset
inteiro client-side antes de qualquer `fetch*`. Este benchmark mede, contra
uma tabela sintética de escala comparável (1M linhas, ~150 bytes/linha):

1. `PercentualDeLinhas(10)` sem streaming (o comportamento pré-issue) vs.
   com streaming forçado (`monkeypatch` do limiar pra 0) — isola o efeito
   do streaming sozinho, sem trocar de estratégia.
2. `PercentualDeLinhas(10)` vs. `AmostragemPorFaixa(10)`, as duas sem
   streaming forçado (limiares padrão) — isola o efeito da estratégia mais
   barata sozinha, sem streaming.

Cada medição roda num subprocesso isolado (`resource.getrusage` é
acumulado por processo, não reseta entre chamadas) — sem isso, medir duas
configurações na mesma sessão pytest contaminaria o RSS de pico de uma com
o resíduo da outra.

Ressalva de medição, mesma dos demais benchmarks do projeto: Docker local
tem I/O mais rápido que um Postgres gerenciado real — os tempos absolutos
são um PISO, não uma previsão de produção. RSS de pico é mais estável
entre ambientes que tempo de parede, mas ainda depende de `page cache`/SO.

Este benchmark é o critério de calibração dos limiares de streaming
(`_LIMIAR_LINHAS_STREAMING`/`_LIMIAR_BYTES_STREAMING`, hoje só candidatos
em `extractors/comum/ler_amostra_em_lotes.py`) e não fixa valores sozinho
— os resultados impressos aqui (rodar com `-s`) orientam a calibração
manual, feita depois, à parte.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/postgres/test_extrator_postgres_benchmark_streaming.py
"""

import subprocess
import sys
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.benchmark

_N_LINHAS = 1_000_000

# TEXT de ~120 bytes fixos + colunas numéricas/timestamp: ~150 bytes/linha
# médios, mesma ordem de grandeza da tabela real que motivou a issue
# (token_acesso: 778MB / 4.118.390 linhas ≈ 189 bytes/linha).
_DDL_OUTLIER = f"""
    CREATE TABLE public.tabela_outlier (
        id INTEGER PRIMARY KEY,
        token TEXT NOT NULL,
        valor NUMERIC(10, 2) NOT NULL,
        criado_em TIMESTAMP NOT NULL DEFAULT now(),
        ativo BOOLEAN NOT NULL
    );

    INSERT INTO public.tabela_outlier (id, token, valor, ativo)
    SELECT
        g,
        rpad('tok_' || g, 120, 'x'),
        (g % 1000)::numeric / 10,
        g % 2 = 0
    FROM generate_series(1, {_N_LINHAS}) AS g;

    ANALYZE public.tabela_outlier;
"""


@pytest.fixture(scope="module")
def dsn_outlier() -> Iterator[str]:
    """Sobe um Postgres descartável e semeia a tabela outlier sintética."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_DDL_OUTLIER)
        yield url


def _medir_em_subprocesso(
    dsn: str, estrategia_codigo: str, forcar_streaming: bool
) -> tuple[float, int, int]:
    """Roda extrair_tabela num subprocesso isolado, medindo tempo e RSS de pico.

    Subprocesso isolado é essencial aqui: `resource.getrusage(...).ru_maxrss`
    é o pico acumulado do processo inteiro desde que ele começou, não reseta
    entre chamadas — medir duas configurações na mesma sessão Python faria a
    2ª sempre "herdar" o pico da 1ª.

    Args:
        dsn: string de conexão do Postgres já semeado.
        estrategia_codigo: expressão Python que constrói a Estrategia
            (ex.: `"PercentualDeLinhas(percentual=10)"`).
        forcar_streaming: quando True, derruba o limiar de linhas do
            streaming pra 0 antes de extrair — qualquer tabela não vazia
            ativa o cursor nomeado.

    Returns:
        (tempo_segundos, tamanho_amostra, pico_rss_kb).
    """
    codigo = f"""
import resource
import time

import ddf.infrastructure.adapters.outbounds.extractors.comum.ler_amostra_em_lotes as streaming
import ddf.infrastructure.adapters.outbounds.extractors.estrategias.amostragem_por_faixa as m1
import ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas as m2
import ddf.infrastructure.adapters.outbounds.extractors.postgres.extrator_postgres as m3
import ddf.domain.model.common.configuracao_de_extracao as m4

AmostragemPorFaixa = m1.AmostragemPorFaixa
PercentualDeLinhas = m2.PercentualDeLinhas
ExtratorPostgres = m3.ExtratorPostgres
ConfiguracaoDeExtracao = m4.ConfiguracaoDeExtracao

if {forcar_streaming!r}:
    streaming._LIMIAR_LINHAS_STREAMING = 0

configuracao = ConfiguracaoDeExtracao(estrategia={estrategia_codigo})
extrator = ExtratorPostgres(dsn={dsn!r}, configuracao=configuracao)

inicio = time.perf_counter()
resultado = extrator.extrair_tabela("public", "tabela_outlier")
tempo = time.perf_counter() - inicio

assert resultado.__class__.__name__ == "Sucesso", resultado
pico_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
tamanho_amostra = resultado.valor.metadados_amostra.tamanho_amostra
print(f"RESULTADO {{tempo}} {{tamanho_amostra}} {{pico_rss_kb}}")
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
    _, tempo_str, tamanho_amostra_str, pico_rss_str = linha_resultado.split()
    return float(tempo_str), int(tamanho_amostra_str), int(pico_rss_str)


def _imprimir_linha(rotulo: str, tempo: float, amostra: int, rss_kb: int) -> None:
    """Formata uma linha da tabela de resultados do benchmark."""
    rss_mb = rss_kb / 1024
    print(f"{rotulo:<22} | {tempo:>8.3f} | {amostra:>7} | {rss_mb:>10.1f}")


def test_benchmark_streaming_reduz_rss_de_pico_em_tabela_outlier(
    dsn_outlier: str,
) -> None:
    """Isola o efeito do streaming: mesma estratégia, com e sem cursor nomeado.

    Hipótese (achado empírico da issue): sem streaming, `fetchall()` de
    ~10% de 1M linhas materializa o resultset inteiro client-side antes de
    qualquer `fetch`, inflando RSS de pico bem acima do que a amostra final
    ocupa. Com streaming, o pico deveria ficar mais próximo do tamanho real
    da amostra, não da tabela inteira varrida.
    """
    tempo_sem, amostra_sem, rss_sem = _medir_em_subprocesso(
        dsn_outlier,
        "PercentualDeLinhas(percentual=10, seed=42)",
        forcar_streaming=False,
    )
    tempo_com, amostra_com, rss_com = _medir_em_subprocesso(
        dsn_outlier,
        "PercentualDeLinhas(percentual=10, seed=42)",
        forcar_streaming=True,
    )

    print("\nconfiguração           | tempo(s) | amostra | RSS pico(MB)")
    _imprimir_linha("sem streaming", tempo_sem, amostra_sem, rss_sem)
    _imprimir_linha("com streaming forçado", tempo_com, amostra_com, rss_com)
    print(f"\nredução de RSS: {(1 - rss_com / rss_sem) * 100:.1f}%")

    # Mesma amostra lógica nos dois — só o caminho de leitura muda.
    assert amostra_sem == amostra_com


def test_benchmark_amostragem_por_faixa_vs_percentual_de_linhas(
    dsn_outlier: str,
) -> None:
    """Isola o efeito da estratégia mais barata: sem streaming forçado nos dois.

    Hipótese (issue): AmostragemPorFaixa via TABLESAMPLE SYSTEM lê só as
    páginas sorteadas (~O(percentual)), enquanto PercentualDeLinhas via
    TABLESAMPLE BERNOULLI varre a tabela inteira decidindo linha a linha
    (~O(total_linhas)) — o tempo de PercentualDeLinhas não deveria cair
    proporcionalmente ao percentual pedido, o de AmostragemPorFaixa sim.
    """
    tempo_percentual, amostra_percentual, rss_percentual = _medir_em_subprocesso(
        dsn_outlier,
        "PercentualDeLinhas(percentual=10)",
        forcar_streaming=False,
    )
    tempo_faixa, amostra_faixa, rss_faixa = _medir_em_subprocesso(
        dsn_outlier,
        "AmostragemPorFaixa(percentual=10)",
        forcar_streaming=False,
    )

    print("\nestratégia             | tempo(s) | amostra | RSS pico(MB)")
    _imprimir_linha(
        "PercentualDeLinhas", tempo_percentual, amostra_percentual, rss_percentual
    )
    _imprimir_linha("AmostragemPorFaixa", tempo_faixa, amostra_faixa, rss_faixa)
    print(f"\nganho de tempo: {tempo_percentual / tempo_faixa:.2f}x")

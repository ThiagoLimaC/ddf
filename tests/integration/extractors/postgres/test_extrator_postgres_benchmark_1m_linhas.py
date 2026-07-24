"""Benchmark: tempo de extração de uma tabela real com 1M linhas (issue #56).

Mede o tempo de parede de `ExtratorPostgres.extrair_tabela` contra uma
tabela sintética de 1.000.000 de linhas, em diferentes `percentual`es de
`PercentualDeLinhas`. A hipótese sob teste é a limitação documentada em
`docs/system_design_doc.md` (linhas 130-136): `PercentualDeLinhas` faz
`TABLESAMPLE BERNOULLI`, que varre a tabela inteira independente do
percentual pedido — logo o tempo deveria ficar ~constante entre
percentual=1 e percentual=50, não cair proporcionalmente.

Ressalva de medição: Docker local (socket loopback) tem I/O mais rápido e
menos latência que um Postgres gerenciado real — os tempos absolutos aqui
são um PISO, não uma previsão de produção. O que importa é a FORMA da
curva (tempo x percentual), que é o que a hipótese prevê.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s tests/integration/extractors/postgres/test_extrator_postgres_benchmark_1m_linhas.py
"""

import time
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

pytestmark = pytest.mark.benchmark

_N_LINHAS = 1_000_000
_PERCENTUAIS = [1, 10, 50, 100]

_DDL_1M_LINHAS = f"""
    CREATE TABLE public.tabela_1m (
        id INTEGER PRIMARY KEY,
        nome TEXT NOT NULL,
        valor NUMERIC(10, 2) NOT NULL,
        criado_em TIMESTAMP NOT NULL DEFAULT now(),
        ativo BOOLEAN NOT NULL
    );

    INSERT INTO public.tabela_1m (id, nome, valor, ativo)
    SELECT
        g,
        'linha_' || g,
        (g % 1000)::numeric / 10,
        g % 2 = 0
    FROM generate_series(1, {_N_LINHAS}) AS g;

    ANALYZE public.tabela_1m;
"""


@pytest.fixture(scope="module")
def dsn_1m_linhas() -> Iterator[str]:
    """Sobe um Postgres descartável e semeia uma tabela com 1M linhas."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_DDL_1M_LINHAS)
        yield url


def test_benchmark_extracao_tabela_1m_linhas_por_percentual(
    dsn_1m_linhas: str,
) -> None:
    """Mede tempo de extrair_tabela em 1M linhas, variando o percentual pedido.

    Confirma (ou refuta) a hipótese de full scan: se o tempo não cai
    proporcionalmente ao percentual, a extração está dominada pela
    varredura da tabela inteira, não pelo tamanho da amostra resultante.
    """
    print("\npercentual | tamanho_amostra | tempo(s)")

    tempos: dict[int, float] = {}
    for percentual in _PERCENTUAIS:
        configuracao = ConfiguracaoDeExtracao(
            estrategia=PercentualDeLinhas(percentual=percentual)
        )
        extrator = ExtratorPostgres(dsn=dsn_1m_linhas, configuracao=configuracao)

        inicio = time.perf_counter()
        resultado = extrator.extrair_tabela("public", "tabela_1m")
        tempo = time.perf_counter() - inicio

        assert isinstance(resultado, Sucesso)
        tamanho_amostra = resultado.valor.metadados_amostra.tamanho_amostra
        tempos[percentual] = tempo

        print(f"{percentual:>10} | {tamanho_amostra:>15} | {tempo:>8.3f}")

    # Hipótese de full scan (issue #56): tempo com percentual=1 não deveria
    # ser ordens de magnitude menor que percentual=100 — se fosse
    # proporcional ao tamanho da amostra, teria ~1% do tempo.
    razao = tempos[1] / tempos[100] if tempos[100] > 0 else float("inf")
    print(f"\nrazão tempo(1%) / tempo(100%) = {razao:.2f} (esperado: próximo de 1.0)")

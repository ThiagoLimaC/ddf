"""Spike de validação técnica — Fase 0 da issue #126 (paralelismo intra-tabela).

Pergunta que este spike resolve, registrada em
`plan/registry-plan/issue-126-paralelismo-intra-tabela.md`: uma leitura
particionada por `ctid` (blocos físicos) reduz de fato os blocos lidos pelo
Postgres, ou o predicado `ctid` é só um filtro aplicado depois de uma
varredura completa? Decide se o paralelismo intra-tabela cobre as 3
Estrategias de amostragem (via A — `TABLESAMPLE` combinado com `ctid`) ou só
`AmostragemIntegral`/leitura física completa por partição com a amostragem
aplicada depois em Polars (via B — sem `TABLESAMPLE` na query, só `ctid`).

Isolamento de cache: cada medição roda contra uma tabela **fisicamente
distinta** (mesmos dados, `relfilenode` próprio) — evita que uma consulta
"aqueça" o `shared_buffers` que a consulta seguinte reaproveitaria,
mascarando a diferença real de blocos tocados (achado do engenheiro de
dados na banca de revisão do plano: comparar as duas queries na mesma
tabela/sessão inflaria artificialmente o ganho da 2ª). Como cada tabela
nunca foi tocada antes por este Postgres, todo buffer que ela usa
necessariamente vem de disco (`read`), nunca de cache (`hit`) — dispensa
reiniciar o container entre medições.

Não testa contenção de I/O físico sob concorrência real (M workers
simultâneos) — isso só é coberto, parcialmente, pelo benchmark de
performance previsto no item 8 do checklist da issue, sujeito à mesma
ressalva de Docker local vs. produção já registrada na investigação
original da #126.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/postgres/test_spike_paralelismo_intra_tabela.py
"""

import re
from collections.abc import Iterator

import psycopg2
import pytest
from psycopg2.extensions import connection as conexao_postgres
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.benchmark

_N_LINHAS = 200_000


def _ddl_tabela(nome: str) -> str:
    """DDL de uma tabela sintética de ~200k linhas, larga o bastante pra ter
    milhares de blocos de 8KB — sem isso, uma faixa de 1/4 da tabela não
    teria granularidade suficiente pra distinguir "leu tudo" de "leu 1/4".
    """  # noqa: D205
    return f"""
        CREATE TABLE public.{nome} (
            id INTEGER PRIMARY KEY,
            valor TEXT NOT NULL
        );
        INSERT INTO public.{nome} (id, valor)
        SELECT g, rpad('v' || g, 80, 'x')
        FROM generate_series(1, {_N_LINHAS}) AS g;
        ANALYZE public.{nome};
    """


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    """Sobe um Postgres 16 descartável — as tabelas são criadas por teste."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield container.get_connection_url()


def _criar_tabela_isolada(conexao: conexao_postgres, nome: str) -> None:
    """Cria uma tabela nunca antes tocada — garante blocos frios no cache."""
    with conexao.cursor() as cursor:
        cursor.execute(_ddl_tabela(nome))


def _blocos_totais(conexao: conexao_postgres, tabela: str) -> int:
    """Total de blocos de 8KB da tabela, via pg_relation_size/block_size."""
    with conexao.cursor() as cursor:
        cursor.execute(
            "SELECT pg_relation_size(%s::regclass) "
            "/ current_setting('block_size')::int",
            (f"public.{tabela}",),
        )
        linha = cursor.fetchone()
        assert linha is not None
        return int(linha[0])


def _explain_buffers(conexao: conexao_postgres, sql: str) -> dict[str, object]:
    """Roda EXPLAIN (ANALYZE, BUFFERS) e soma shared hit/read de todo o plano."""
    with conexao.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}")
        linhas = [str(linha[0]) for linha in cursor.fetchall()]
    texto = "\n".join(linhas)
    hits = sum(int(n) for n in re.findall(r"shared hit=(\d+)", texto))
    reads = sum(int(n) for n in re.findall(r"read=(\d+)", texto))
    return {"hit": hits, "read": reads, "texto": texto}


def _reportar(
    rotulo: str,
    total_blocos: int,
    limite_faixa: int,
    completa: dict[str, object],
    faixa: dict[str, object],
) -> None:
    """Imprime o resultado comparativo de uma rodada do spike (rodar com -s)."""
    blocos_completa = int(completa["hit"]) + int(completa["read"])  # type: ignore[call-overload]
    blocos_faixa = int(faixa["hit"]) + int(faixa["read"])  # type: ignore[call-overload]
    razao = blocos_faixa / max(1, blocos_completa)
    print(f"\n=== {rotulo} ===")
    print(f"total_blocos={total_blocos}, limite_faixa(1/4)={limite_faixa}")
    print(f"completa: read={completa['read']} hit={completa['hit']}")
    print(f"faixa (1/4): read={faixa['read']} hit={faixa['hit']}")
    print(f"razão faixa/completa: {razao:.2f} (esperado ~0.25 se reduz blocos)")
    print(f"\nplano da faixa:\n{faixa['texto']}")


def test_spike_ctid_range_scan_sem_tablesample(dsn: str) -> None:
    """Via B: leitura física por faixa de ctid, sem TABLESAMPLE.

    Pré-requisito de qualquer paralelismo intra-tabela: se isto não reduzir
    blocos tocados, nem a via B (ler a partição inteira, filtrar depois em
    Polars) funciona, e o paralelismo intra-tabela inteiro fica inviável —
    o caso mais simples possível (sem amostragem nenhuma) precisa funcionar
    primeiro.
    """
    with psycopg2.connect(dsn) as conexao_setup:
        conexao_setup.autocommit = True
        _criar_tabela_isolada(conexao_setup, "tabela_ctid_completa")
        _criar_tabela_isolada(conexao_setup, "tabela_ctid_faixa")
        total_blocos = _blocos_totais(conexao_setup, "tabela_ctid_completa")

    limite_faixa = total_blocos // 4

    with psycopg2.connect(dsn) as conexao:
        conexao.autocommit = True
        completa = _explain_buffers(
            conexao, "SELECT * FROM public.tabela_ctid_completa"
        )
        faixa = _explain_buffers(
            conexao,
            "SELECT * FROM public.tabela_ctid_faixa "
            f"WHERE ctid < '({limite_faixa},0)'::tid",
        )

    _reportar(
        "via B — ctid puro, sem TABLESAMPLE",
        total_blocos,
        limite_faixa,
        completa,
        faixa,
    )


def test_spike_tablesample_system_com_ctid(dsn: str) -> None:
    """Via A (SYSTEM): TABLESAMPLE SYSTEM combinado com predicado ctid.

    Usado por `AmostragemPorFaixa`/`RequisicaoPorFaixa` hoje — decide se
    essa Estrategia também é elegível a paralelismo intra-tabela.
    """
    with psycopg2.connect(dsn) as conexao_setup:
        conexao_setup.autocommit = True
        _criar_tabela_isolada(conexao_setup, "tabela_system_completa")
        _criar_tabela_isolada(conexao_setup, "tabela_system_faixa")
        total_blocos = _blocos_totais(conexao_setup, "tabela_system_completa")

    limite_faixa = total_blocos // 4

    with psycopg2.connect(dsn) as conexao:
        conexao.autocommit = True
        completa = _explain_buffers(
            conexao,
            "SELECT * FROM public.tabela_system_completa "
            "TABLESAMPLE SYSTEM (10) REPEATABLE (1)",
        )
        faixa = _explain_buffers(
            conexao,
            "SELECT * FROM public.tabela_system_faixa "
            "TABLESAMPLE SYSTEM (10) REPEATABLE (1) "
            f"WHERE ctid < '({limite_faixa},0)'::tid",
        )

    _reportar(
        "via A — TABLESAMPLE SYSTEM + ctid",
        total_blocos,
        limite_faixa,
        completa,
        faixa,
    )


def test_spike_tablesample_bernoulli_com_ctid(dsn: str) -> None:
    """Via A (BERNOULLI): TABLESAMPLE BERNOULLI combinado com predicado ctid.

    Usado por `PercentualDeLinhas`/`AmostragemProbabilistica` hoje.
    BERNOULLI decide por linha (não por bloco, como SYSTEM) — mesmo que
    SYSTEM funcione com `ctid`, BERNOULLI pode ter um plano de execução
    diferente e precisa de validação própria.
    """
    with psycopg2.connect(dsn) as conexao_setup:
        conexao_setup.autocommit = True
        _criar_tabela_isolada(conexao_setup, "tabela_bernoulli_completa")
        _criar_tabela_isolada(conexao_setup, "tabela_bernoulli_faixa")
        total_blocos = _blocos_totais(conexao_setup, "tabela_bernoulli_completa")

    limite_faixa = total_blocos // 4

    with psycopg2.connect(dsn) as conexao:
        conexao.autocommit = True
        completa = _explain_buffers(
            conexao,
            "SELECT * FROM public.tabela_bernoulli_completa "
            "TABLESAMPLE BERNOULLI (10) REPEATABLE (1)",
        )
        faixa = _explain_buffers(
            conexao,
            "SELECT * FROM public.tabela_bernoulli_faixa "
            "TABLESAMPLE BERNOULLI (10) REPEATABLE (1) "
            f"WHERE ctid < '({limite_faixa},0)'::tid",
        )

    _reportar(
        "via A — TABLESAMPLE BERNOULLI + ctid",
        total_blocos,
        limite_faixa,
        completa,
        faixa,
    )

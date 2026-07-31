"""Benchmark sintético de ExtratorPostgres: throughput da consolidação (#66).

Mede o custo das queries de metadado (colunas, PK, FK, UNIQUE, total_linhas)
"antes" (5 queries por tabela, filtradas por table_name — o padrão removido
por esta issue) vs "depois" (5 queries por schema inteiro, cacheadas — o
padrão atual de `ExtratorPostgres._obter_metadados_schema`), contra um
schema sintético com 10/50/100/200 tabelas espalhadas em alguns schemas.

Ressalva de medição: Docker local tem round-trip sub-milissegundo (socket
loopback); Postgres gerenciado real fica em 0,3-2ms por round-trip (mais em
cross-AZ). O tempo medido aqui é um PISO conservador do ganho — a proporção
de queries eliminadas (determinística, não depende de latência de rede) é a
evidência mais forte; o tempo de parede é só ilustrativo.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts) — é oneroso
(cria até 200 tabelas) e sua asserção central é sobre nº de round-trips, não
sobre tempo de parede, que é ruidoso mesmo em Docker. Rodar explicitamente:

    uv run pytest -m benchmark -s tests/integration/extractors/postgres
"""

import time
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

pytestmark = pytest.mark.benchmark

_N_SCHEMAS = 4
_PONTOS_DE_TABELAS = [10, 50, 100, 200]

# As 4 queries abaixo são a réplica fiel do padrão "antes" da issue #66 —
# per-tabela, filtradas por table_name — removido de src/ nesta mesma issue.
# Vivem só aqui, como baseline de benchmark, não como código de produção.
_COLUNAS_SQL_ANTIGA = """
    SELECT column_name, udt_name, character_maximum_length,
           numeric_precision, numeric_scale, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
"""

_CHAVES_PRIMARIAS_SQL_ANTIGA = """
    SELECT kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

_CHAVES_ESTRANGEIRAS_SQL_ANTIGA = """
    SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
        AND tc.constraint_schema = rc.constraint_schema
    JOIN information_schema.key_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
        AND rc.unique_constraint_schema = ccu.constraint_schema
        AND kcu.position_in_unique_constraint = ccu.ordinal_position
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

_COLUNAS_UNICAS_SQL_ANTIGA = """
    SELECT a.attname
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
    WHERE i.indisunique AND NOT i.indisprimary
        AND array_length(i.indkey, 1) = 1
        AND n.nspname = %s AND t.relname = %s
"""

# Sem relkind — fiel ao "antes": o filtro relkind IN ('r', 'p') é parte do
# que a issue #66 introduziu, não do baseline que ela substitui.
_TOTAL_LINHAS_SQL_ANTIGA = """
    SELECT reltuples
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s
"""


def _gerar_ddl_sintetico(
    n_tabelas: int,
) -> tuple[list[str], list[tuple[str, str]], str]:
    """Gera schemas/tabelas sintéticos com PK, FK e UNIQUE avulso.

    FK cobre 3 formas: cadeia dentro do schema, cross-schema (a cada 10
    tabelas) e uma auto-referência (1ª tabela do 1º schema). 5-20 colunas
    por tabela.

    Returns:
        (nomes_dos_schemas, [(schema, tabela), ...] em ordem de criação, DDL).
    """
    schemas = [f"bench_{i}" for i in range(_N_SCHEMAS)]
    tabelas = [
        (schemas[indice % _N_SCHEMAS], f"t{indice}") for indice in range(n_tabelas)
    ]

    comandos = [f"CREATE SCHEMA {schema};" for schema in schemas]

    for indice, (schema, tabela) in enumerate(tabelas):
        colunas = ["id SERIAL PRIMARY KEY"]

        # Auto-referência: só a 1ª tabela do 1º schema.
        if indice == 0:
            colunas.append(f"parent_id INTEGER REFERENCES {schema}.{tabela}(id)")

        # FK em cadeia dentro do schema, a partir da 2ª tabela de cada um.
        indice_anterior = indice - _N_SCHEMAS
        if indice_anterior >= 0:
            schema_ref, tabela_ref = tabelas[indice_anterior]
            colunas.append(f"ref_id INTEGER REFERENCES {schema_ref}.{tabela_ref}(id)")

        # FK cross-schema a cada 10 tabelas, pra 1ª tabela do schema anterior.
        if indice % 10 == 9:
            schema_pos = indice % _N_SCHEMAS
            schema_cruzado, tabela_cruzada = tabelas[(schema_pos - 1) % _N_SCHEMAS]
            colunas.append(
                f"cross_ref_id INTEGER REFERENCES {schema_cruzado}.{tabela_cruzada}(id)"
            )

        # UNIQUE avulso a cada 5 tabelas.
        if indice % 5 == 4:
            colunas.append("codigo TEXT UNIQUE")

        n_colunas_extra = 4 + (indice % 16)  # completa pra faixa 5-20 colunas
        for c in range(n_colunas_extra):
            tipo = "INTEGER" if c % 2 == 0 else "TEXT"
            colunas.append(f"col_{c} {tipo}")

        colunas_sql = ",\n            ".join(colunas)
        comandos.append(
            f"CREATE TABLE {schema}.{tabela} (\n            {colunas_sql}\n        );"
        )
        comandos.append(f"INSERT INTO {schema}.{tabela} DEFAULT VALUES;")

    for schema, tabela in tabelas:
        comandos.append(f"ANALYZE {schema}.{tabela};")

    return schemas, tabelas, "\n".join(comandos)


@pytest.fixture(scope="module")
def dsn_sintetico() -> Iterator[str]:
    """Sobe um Postgres descartável e semeia o maior conjunto sintético (200 tabelas).

    Sessão única reaproveitada pelos 4 pontos do benchmark — cada ponto usa
    só um prefixo das tabelas já criadas (mesma ordem de _gerar_ddl_sintetico),
    evitando recriar o schema do zero 4 vezes.
    """
    schemas, tabelas, ddl = _gerar_ddl_sintetico(max(_PONTOS_DE_TABELAS))
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(ddl)
        yield url


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """ConfiguracaoDeExtracao mínima — o benchmark não olha a amostra."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=1))


def _medir_antes(dsn: str, tabelas: list[tuple[str, str]]) -> float:
    """Roda as 5 queries antigas, filtradas por tabela, pra cada tabela do lote."""
    inicio = time.perf_counter()
    with psycopg2.connect(dsn) as conexao:
        conexao.autocommit = True
        with conexao.cursor() as cursor:
            for schema, tabela in tabelas:
                cursor.execute(_COLUNAS_SQL_ANTIGA, (schema, tabela))
                cursor.fetchall()
                cursor.execute(_CHAVES_PRIMARIAS_SQL_ANTIGA, (schema, tabela))
                cursor.fetchall()
                cursor.execute(_CHAVES_ESTRANGEIRAS_SQL_ANTIGA, (schema, tabela))
                cursor.fetchall()
                cursor.execute(_COLUNAS_UNICAS_SQL_ANTIGA, (schema, tabela))
                cursor.fetchall()
                cursor.execute(_TOTAL_LINHAS_SQL_ANTIGA, (schema, tabela))
                cursor.fetchall()
    return time.perf_counter() - inicio


def _medir_depois(
    dsn: str, configuracao: ConfiguracaoDeExtracao, tabelas: list[tuple[str, str]]
) -> tuple[float, int]:
    """Roda _obter_metadados_schema pra cada tabela do lote (cache-aware).

    Returns:
        (tempo total, nº de schemas efetivamente populados no cache).
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)
    inicio = time.perf_counter()
    for schema, _tabela in tabelas:
        resultado = extrator._obter_metadados_schema(schema)
        assert isinstance(resultado, Sucesso)
    tempo = time.perf_counter() - inicio
    return tempo, len(extrator._cache_schemas)


def test_benchmark_consolidacao_de_metadados_por_schema(
    dsn_sintetico: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Compara nº de round-trips e tempo de parede, antes/depois, em 4 pontos.

    A asserção central é determinística (nº de schemas cacheados == nº de
    schemas distintos no lote, nunca nº de tabelas) — o tempo de parede é
    reportado via print (rodar com -s), não é o critério de aprovação, dado
    o piso conservador de Docker local documentado no topo do arquivo.
    """
    _, todas_as_tabelas, _ = _gerar_ddl_sintetico(max(_PONTOS_DE_TABELAS))

    print(
        "\nn_tabelas | schemas | q.antes | q.depois | t_antes(s) | t_depois(s) | ganho"
    )
    for n_tabelas in _PONTOS_DE_TABELAS:
        lote = todas_as_tabelas[:n_tabelas]
        n_schemas_no_lote = len({schema for schema, _ in lote})

        tempo_antes = _medir_antes(dsn_sintetico, lote)
        tempo_depois, schemas_cacheados = _medir_depois(
            dsn_sintetico, configuracao, lote
        )

        queries_antes = 5 * n_tabelas
        queries_depois = 5 * n_schemas_no_lote
        ganho = tempo_antes / tempo_depois if tempo_depois > 0 else float("inf")

        print(
            f"{n_tabelas:>9} | {n_schemas_no_lote:>7} | {queries_antes:>7} | "
            f"{queries_depois:>8} | {tempo_antes:>10.4f} | {tempo_depois:>11.4f} | "
            f"{ganho:>4.1f}x"
        )

        # Determinístico: o cache tem 1 entrada por schema do lote, nunca 1
        # por tabela — é essa razão, não o tempo de parede, que garante o
        # ganho estrutural independente da latência de rede do ambiente.
        assert schemas_cacheados == n_schemas_no_lote
        assert queries_depois <= queries_antes

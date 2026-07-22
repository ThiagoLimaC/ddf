"""Extrator concreto para bancos Postgres."""

import threading
from typing import NamedTuple

import polars as pl
from psycopg2 import OperationalError, sql
from psycopg2.pool import ThreadedConnectionPool

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)

_LISTAR_ESCOPOS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
      AND schema_name NOT LIKE 'pg_temp_%'
      AND schema_name NOT LIKE 'pg_toast_temp_%'
    ORDER BY schema_name
"""

_LISTAR_TABELAS_SQL = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COLUNAS_SQL = """
    SELECT column_name, udt_name, character_maximum_length,
           numeric_precision, numeric_scale, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
"""

_CHAVES_PRIMARIAS_SQL = """
    SELECT kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

_CHAVES_ESTRANGEIRAS_SQL = """
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

_TOTAL_LINHAS_SQL = """
    SELECT reltuples
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s
"""

# Via pg_index (catálogo), não information_schema.table_constraints como
# PK/FK acima: todo UNIQUE constraint no Postgres é backed por um índice em
# pg_index, então esta única query cobre tanto constraint UNIQUE nomeada
# quanto CREATE UNIQUE INDEX solto (sem ADD CONSTRAINT) — o segundo caso não
# aparece em information_schema.table_constraints de jeito nenhum.
# NOT i.indisprimary exclui PK sem lógica extra: o índice de suporte de uma
# PK nunca aparece como uma segunda entrada indisunique "solta".
_COLUNAS_UNICAS_SQL = """
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


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SQL — construir a tupla (`_LinhaColuna(*linha)`) é o único
    ponto onde essa correspondência posicional existe; daqui pra frente,
    todo o código lê por nome (`linha.udt_name`), não por índice.
    """

    nome: str
    udt_name: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None
    is_nullable: str


def _construir_coluna(
    linha: _LinhaColuna,
    colunas_pk: set[str],
    colunas_fk: dict[str, ReferenciaDeColuna],
    colunas_unicas: set[str],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK/UNIQUE já lidas."""
    referencia = colunas_fk.get(linha.nome)
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=mapear_tipo_postgres(
            linha.udt_name,
            linha.tamanho_maximo,
            linha.precisao,
            linha.escala,
        ),
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=referencia is not None,
        referencia=referencia,
        nao_nulavel=linha.is_nullable == "NO",
        unica=linha.nome in colunas_unicas,
    )


class ExtratorPostgres:
    """Extrai estrutura e amostra de tabelas de um banco Postgres."""

    def __init__(
        self,
        dsn: str,
        configuracao: ConfiguracaoDeExtracao,
        max_conexoes: int = 8,
    ) -> None:
        """Guarda os parâmetros de conexão — o pool só é criado no primeiro uso.

        Args:
            dsn: string de conexão do Postgres.
            configuracao: política de amostragem, agnóstica de fonte.
            max_conexoes: nº máximo de conexões simultâneas que este Postgres
                aguenta com segurança — dimensiona o pool e o semáforo interno
                que impede o esgotamento do pool sob chamadas concorrentes.

        Raises:
            ValueError: se `max_conexoes` não for positivo.
        """
        if max_conexoes <= 0:
            raise ValueError(f"max_conexoes deve ser positivo ({max_conexoes}).")
        self._dsn = dsn
        self._configuracao = configuracao
        self._max_conexoes = max_conexoes
        self._pool: ThreadedConnectionPool | None = None
        self._semaforo = threading.Semaphore(max_conexoes)
        self._lock_pool = threading.Lock()

    def _obter_pool(self) -> Resultado[ThreadedConnectionPool]:
        """Cria o pool sob demanda, pra falha de conexão virar Falha, não exceção."""
        if self._pool is None:
            with self._lock_pool:
                if self._pool is None:
                    try:
                        self._pool = ThreadedConnectionPool(
                            minconn=1,
                            maxconn=self._max_conexoes,
                            dsn=self._dsn,
                        )
                    except OperationalError as erro:
                        return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (schemas) disponíveis, ordenados por nome."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            self._semaforo.release()
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_ESCOPOS_SQL)
                escopos: list[str] = []
                for linha_escopo in cursor.fetchall():
                    nome_schema = linha_escopo[0]
                    escopos.append(nome_schema)
            return Sucesso(escopos)
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

    def listar_tabelas(self, schema: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (schema, nome_tabela) do schema informado, ordenado por nome_tabela."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            self._semaforo.release()
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_TABELAS_SQL, (schema,))
                tabelas: list[tuple[str, str]] = []
                for linha_tabela in cursor.fetchall():
                    nome_schema, nome_tabela = linha_tabela
                    tabelas.append((nome_schema, nome_tabela))
            return Sucesso(tabelas)
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

    def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            self._semaforo.release()
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_COLUNAS_SQL, (schema, tabela))
                linhas_colunas: list[_LinhaColuna] = []
                for linha_bruta in cursor.fetchall():
                    linhas_colunas.append(_LinhaColuna(*linha_bruta))
                if not linhas_colunas:
                    return Falha(
                        f"Schema '{schema}' ou tabela '{tabela}' não encontrada."
                    )

                cursor.execute(_CHAVES_PRIMARIAS_SQL, (schema, tabela))
                colunas_pk: set[str] = set()
                for linha_pk in cursor.fetchall():
                    nome_coluna_pk = linha_pk[0]
                    colunas_pk.add(nome_coluna_pk)

                cursor.execute(_CHAVES_ESTRANGEIRAS_SQL, (schema, tabela))
                colunas_fk, avisos = construir_colunas_fk(
                    cursor.fetchall(), origem="ExtratorPostgres"
                )

                cursor.execute(_COLUNAS_UNICAS_SQL, (schema, tabela))
                colunas_unicas: set[str] = set()
                for linha_unica in cursor.fetchall():
                    colunas_unicas.add(linha_unica[0])

                colunas: list[ColunaExtraida] = []
                for linha_coluna in linhas_colunas:
                    colunas.append(
                        _construir_coluna(
                            linha_coluna, colunas_pk, colunas_fk, colunas_unicas
                        )
                    )

                cursor.execute(_TOTAL_LINHAS_SQL, (schema, tabela))
                linha_total = cursor.fetchone()
                total_linhas = max(0, round(linha_total[0])) if linha_total else 0

                consulta_amostra = sql.SQL(
                    "SELECT * FROM {}.{} TABLESAMPLE BERNOULLI ({})"
                ).format(
                    sql.Identifier(schema),
                    sql.Identifier(tabela),
                    sql.Literal(self._configuracao.estrategia.percentual),
                )
                cursor.execute(consulta_amostra)
                nomes_colunas: list[str] = []
                for coluna_amostra in cursor.description or ():
                    nomes_colunas.append(coluna_amostra.name)
                linhas_amostra = cursor.fetchall()
                amostra = (
                    pl.DataFrame(
                        linhas_amostra,
                        schema=nomes_colunas,
                        orient="row",
                        infer_schema_length=None,
                    )
                    if linhas_amostra
                    else pl.DataFrame(schema=nomes_colunas)
                )

            metadados_amostra = MetadadosDeAmostra(
                estrategia=self._configuracao.estrategia.nome,
                tamanho_amostra=len(amostra),
            )
            if metadados_amostra.tamanho_amostra > total_linhas:
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"Amostra ({metadados_amostra.tamanho_amostra} linhas) "
                            f"maior que total_linhas ({total_linhas}) — total_linhas "
                            "pode estar desatualizado (sem ANALYZE recente)."
                        ),
                        origem="ExtratorPostgres",
                    )
                )
            return Sucesso(
                TabelaExtraida(
                    nome_tabela=tabela,
                    nome_escopo=schema,
                    colunas=colunas,
                    total_linhas=total_linhas,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                ),
                avisos=avisos,
            )
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

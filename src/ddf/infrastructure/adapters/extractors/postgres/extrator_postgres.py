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
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
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
    SELECT column_name, data_type, character_maximum_length,
           numeric_precision, numeric_scale
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
    JOIN information_schema.constraint_column_usage ccu
        ON tc.constraint_name = ccu.constraint_name
        AND tc.constraint_schema = ccu.constraint_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

_TOTAL_LINHAS_SQL = """
    SELECT reltuples
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s
"""


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SQL — construir a tupla (`_LinhaColuna(*linha)`) é o único
    ponto onde essa correspondência posicional existe; daqui pra frente,
    todo o código lê por nome (`linha.data_type`), não por índice.
    """

    nome: str
    data_type: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None


def _construir_coluna(
    linha: _LinhaColuna,
    colunas_pk: set[str],
    colunas_fk: dict[str, ReferenciaDeColuna],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK já lidas."""
    referencia = colunas_fk.get(linha.nome)
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=mapear_tipo_postgres(
            linha.data_type, linha.tamanho_maximo, linha.precisao, linha.escala
        ),
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=referencia is not None,
        referencia=referencia,
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
                colunas_fk: dict[str, ReferenciaDeColuna] = {}
                for linha_fk in cursor.fetchall():
                    (
                        nome_coluna_fk,
                        escopo_referenciado,
                        tabela_referenciada,
                        coluna_referenciada,
                    ) = linha_fk
                    colunas_fk[nome_coluna_fk] = ReferenciaDeColuna(
                        nome_escopo=escopo_referenciado,
                        nome_tabela=tabela_referenciada,
                        nome_coluna=coluna_referenciada,
                    )

                colunas: list[ColunaExtraida] = []
                for linha_coluna in linhas_colunas:
                    colunas.append(
                        _construir_coluna(linha_coluna, colunas_pk, colunas_fk)
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
                    pl.DataFrame(linhas_amostra, schema=nomes_colunas, orient="row")
                    if linhas_amostra
                    else pl.DataFrame(schema=nomes_colunas)
                )

            metadados_amostra = MetadadosDeAmostra(
                estrategia=self._configuracao.estrategia.nome,
                tamanho_amostra=len(amostra),
            )
            return Sucesso(
                TabelaExtraida(
                    nome_tabela=tabela,
                    nome_escopo=schema,
                    colunas=colunas,
                    total_linhas=total_linhas,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                )
            )
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

"""Extrator concreto para bancos Postgres."""

import polars as pl
from psycopg2 import OperationalError, sql
from psycopg2.pool import ThreadedConnectionPool

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)

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
    SELECT kcu.column_name, ccu.table_name, ccu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
        ON tc.constraint_name = ccu.constraint_name
        AND tc.table_schema = ccu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

_TOTAL_LINHAS_SQL = """
    SELECT reltuples
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s
"""


def _construir_coluna(
    linha: tuple[str, str, int | None, int | None, int | None],
    colunas_pk: set[str],
    colunas_fk: dict[str, tuple[str, str]],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK já lidas."""
    nome, data_type, tamanho_maximo, precisao, escala = linha
    referencia = colunas_fk.get(nome)
    return ColunaExtraida(
        nome=nome,
        tipo_dado=mapear_tipo_postgres(data_type, tamanho_maximo, precisao, escala),
        chave_primaria=nome in colunas_pk,
        chave_estrangeira=referencia is not None,
        tabela_referenciada=referencia[0] if referencia else None,
        coluna_referenciada=referencia[1] if referencia else None,
    )


class ExtratorPostgres:
    """Extrai estrutura e amostra de tabelas de um banco Postgres."""

    def __init__(self, dsn: str, configuracao: ConfiguracaoDeExtracao) -> None:
        """Guarda os parâmetros de conexão — o pool só é criado no primeiro uso.

        Args:
            dsn: string de conexão do Postgres.
            configuracao: parâmetros de concorrência e política de amostragem.
        """
        self._dsn = dsn
        self._configuracao = configuracao
        self._pool: ThreadedConnectionPool | None = None

    def _obter_pool(self) -> Resultado[ThreadedConnectionPool]:
        """Cria o pool sob demanda, pra falha de conexão virar Falha, não exceção."""
        if self._pool is None:
            try:
                self._pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=self._configuracao.max_conexoes,
                    dsn=self._dsn,
                )
            except OperationalError as erro:
                return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    def listar_tabelas(self, schema: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (schema, nome_tabela) do schema informado, ordenado por nome_tabela."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_TABELAS_SQL, (schema,))
                tabelas = [(linha[0], linha[1]) for linha in cursor.fetchall()]
            return Sucesso(tabelas)
        finally:
            pool.putconn(conexao)

    def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_COLUNAS_SQL, (schema, tabela))
                linhas_colunas = cursor.fetchall()
                if not linhas_colunas:
                    return Falha(
                        f"Schema '{schema}' ou tabela '{tabela}' não encontrada."
                    )

                cursor.execute(_CHAVES_PRIMARIAS_SQL, (schema, tabela))
                colunas_pk = {linha[0] for linha in cursor.fetchall()}

                cursor.execute(_CHAVES_ESTRANGEIRAS_SQL, (schema, tabela))
                colunas_fk = {
                    linha[0]: (linha[1], linha[2]) for linha in cursor.fetchall()
                }

                colunas = [
                    _construir_coluna(linha, colunas_pk, colunas_fk)
                    for linha in linhas_colunas
                ]

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
                nomes_colunas = [coluna.name for coluna in cursor.description or ()]
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
                    nome_schema=schema,
                    colunas=colunas,
                    total_linhas=total_linhas,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                )
            )
        finally:
            pool.putconn(conexao)

"""Extrator concreto para bancos MariaDB."""

import threading
from typing import NamedTuple

import polars as pl
import pymysql
from dbutils.pooled_db import PooledDB

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.mariadb.mapeamento_de_tipos import (
    mapear_tipo_mariadb,
)

_LISTAR_ESCOPOS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN
        ('information_schema', 'mysql', 'performance_schema', 'sys')
    ORDER BY schema_name
"""

_LISTAR_TABELAS_SQL = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COLUNAS_SQL = """
    SELECT column_name, data_type, column_type, character_maximum_length,
           numeric_precision, numeric_scale
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
"""

_CHAVES_PRIMARIAS_SQL = """
    SELECT column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s AND constraint_name = 'PRIMARY'
    ORDER BY ordinal_position
"""

_CHAVES_ESTRANGEIRAS_SQL = """
    SELECT column_name, referenced_table_schema, referenced_table_name,
           referenced_column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s
      AND referenced_table_name IS NOT NULL
"""

_TOTAL_LINHAS_SQL = """
    SELECT table_rows
    FROM information_schema.tables
    WHERE table_schema = %s AND table_name = %s
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
    column_type: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None


def _quotar_identificador(nome: str) -> str:
    """Escapa um identificador (schema/tabela) pra uso seguro em SQL cru.

    pymysql não tem um equivalente ao psycopg2.sql.Identifier — crase
    duplicada (` `` `) é a forma do MariaDB de escapar uma crase literal
    dentro de um identificador entre crases.
    """
    return f"`{nome.replace('`', '``')}`"


def _construir_coluna(
    linha: _LinhaColuna,
    colunas_pk: set[str],
    colunas_fk: dict[str, ReferenciaDeColuna],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK já lidas."""
    referencia = colunas_fk.get(linha.nome)
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=mapear_tipo_mariadb(
            linha.data_type,
            linha.column_type,
            linha.tamanho_maximo,
            linha.precisao,
            linha.escala,
        ),
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=referencia is not None,
        referencia=referencia,
    )


def _promover_booleanos_pela_amostra(
    colunas: list[ColunaExtraida],
    amostra: pl.DataFrame,
    candidatos_booleanos: set[str],
) -> list[ColunaExtraida]:
    """Promove INTEGER→BOOLEAN pra colunas tinyint(1) cuja amostra é só 0/1.

    MariaDB não guarda em lugar nenhum a distinção BOOLEAN vs TINYINT(1) —
    é decidido aqui, com base em dado real da própria extração, não em
    convenção de nome de coluna. Amostra vazia ou só nulos não promove:
    falta de evidência não é evidência de booleano.
    """
    colunas_promovidas: list[ColunaExtraida] = []
    for coluna in colunas:
        if coluna.nome in candidatos_booleanos and coluna.nome in amostra.columns:
            valores = amostra[coluna.nome].drop_nulls()
            if valores.len() > 0 and bool(valores.is_in([0, 1]).all()):
                coluna = coluna.model_copy(
                    update={"tipo_dado": TipoDeDado(categoria=CategoriaDeDado.BOOLEAN)}
                )
        colunas_promovidas.append(coluna)
    return colunas_promovidas


class ExtratorMariaDB:
    """Extrai estrutura e amostra de tabelas de um servidor MariaDB.

    Diferente do Postgres, não guarda um "database" default — cada escopo
    (database) é endereçado explicitamente por chamada, já que MariaDB
    colapsa schema e database no mesmo nível.
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        configuracao: ConfiguracaoDeExtracao,
        port: int = 3306,
        max_conexoes: int = 8,
    ) -> None:
        """Guarda os parâmetros de conexão — o pool só é criado no primeiro uso.

        Args:
            host: endereço do servidor MariaDB.
            user: usuário de conexão.
            password: senha de conexão.
            configuracao: política de amostragem, agnóstica de fonte.
            port: porta do servidor MariaDB.
            max_conexoes: nº máximo de conexões simultâneas que este MariaDB
                aguenta com segurança — dimensiona o pool.

        Raises:
            ValueError: se `max_conexoes` não for positivo.
        """
        if max_conexoes <= 0:
            raise ValueError(f"max_conexoes deve ser positivo ({max_conexoes}).")
        self._host = host
        self._user = user
        self._password = password
        self._configuracao = configuracao
        self._port = port
        self._max_conexoes = max_conexoes
        self._pool: PooledDB | None = None
        self._lock_pool = threading.Lock()

    def _obter_pool(self) -> Resultado[PooledDB]:
        """Cria o pool sob demanda, pra falha de conexão virar Falha, não exceção."""
        if self._pool is None:
            with self._lock_pool:
                if self._pool is None:
                    try:
                        self._pool = PooledDB(
                            creator=pymysql,
                            mincached=1,
                            maxcached=self._max_conexoes,
                            maxconnections=self._max_conexoes,
                            blocking=True,
                            host=self._host,
                            port=self._port,
                            user=self._user,
                            password=self._password,
                            autocommit=True,
                        )
                    except pymysql.err.OperationalError as erro:
                        return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (databases) disponíveis, ordenados por nome."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        try:
            conexao = pool.connection()
        except pymysql.err.OperationalError as erro:
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_ESCOPOS_SQL)
                escopos: list[str] = []
                for linha_escopo in cursor.fetchall():
                    nome_escopo = linha_escopo[0]
                    escopos.append(nome_escopo)
            return Sucesso(escopos)
        finally:
            conexao.close()

    def listar_tabelas(self, escopo: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (escopo, nome_tabela) do escopo informado, ordenado por nome_tabela."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        try:
            conexao = pool.connection()
        except pymysql.err.OperationalError as erro:
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_TABELAS_SQL, (escopo,))
                tabelas: list[tuple[str, str]] = []
                for linha_tabela in cursor.fetchall():
                    nome_escopo, nome_tabela = linha_tabela
                    tabelas.append((nome_escopo, nome_tabela))
            return Sucesso(tabelas)
        finally:
            conexao.close()

    def extrair_tabela(self, escopo: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            return resultado_pool
        pool = resultado_pool.valor
        try:
            conexao = pool.connection()
        except pymysql.err.OperationalError as erro:
            return Falha(f"Não foi possível conectar: {erro}")
        try:
            with conexao.cursor() as cursor:
                cursor.execute(_COLUNAS_SQL, (escopo, tabela))
                linhas_colunas: list[_LinhaColuna] = []
                for linha_bruta in cursor.fetchall():
                    linhas_colunas.append(_LinhaColuna(*linha_bruta))
                if not linhas_colunas:
                    return Falha(
                        f"Schema '{escopo}' ou tabela '{tabela}' não encontrada."
                    )

                cursor.execute(_CHAVES_PRIMARIAS_SQL, (escopo, tabela))
                colunas_pk: set[str] = set()
                for linha_pk in cursor.fetchall():
                    nome_coluna_pk = linha_pk[0]
                    colunas_pk.add(nome_coluna_pk)

                cursor.execute(_CHAVES_ESTRANGEIRAS_SQL, (escopo, tabela))
                colunas_fk, avisos = construir_colunas_fk(
                    cursor.fetchall(), origem="ExtratorMariaDB"
                )

                # Colunas só são finalizadas depois da amostra (abaixo) — ao
                # contrário do ExtratorPostgres, aqui a promoção de BOOLEAN
                # depende de dado real já carregado. Ver docstring de
                # _promover_booleanos_pela_amostra.
                candidatos_booleanos: set[str] = set()
                colunas: list[ColunaExtraida] = []
                for linha_coluna in linhas_colunas:
                    # startswith, não == : cobre "tinyint(1) unsigned" além
                    # de "tinyint(1)" — COLUMN_TYPE inclui o modificador
                    # unsigned quando presente, e um tinyint(1) unsigned
                    # também é candidato legítimo a BOOLEAN.
                    if linha_coluna.column_type.startswith("tinyint(1)"):
                        candidatos_booleanos.add(linha_coluna.nome)
                    colunas.append(
                        _construir_coluna(linha_coluna, colunas_pk, colunas_fk)
                    )

                cursor.execute(_TOTAL_LINHAS_SQL, (escopo, tabela))
                linha_total = cursor.fetchone()
                total_linhas = (
                    max(0, round(linha_total[0]))
                    if linha_total and linha_total[0] is not None
                    else 0
                )

                consulta_amostra = (
                    f"SELECT * FROM {_quotar_identificador(escopo)}."
                    f"{_quotar_identificador(tabela)} WHERE RAND() <= %s"
                )
                cursor.execute(
                    consulta_amostra,
                    (self._configuracao.estrategia.percentual / 100,),
                )
                nomes_colunas: list[str] = []
                for coluna_amostra in cursor.description or ():
                    nomes_colunas.append(coluna_amostra[0])
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

                colunas = _promover_booleanos_pela_amostra(
                    colunas, amostra, candidatos_booleanos
                )

            metadados_amostra = MetadadosDeAmostra(
                estrategia=self._configuracao.estrategia.nome,
                tamanho_amostra=len(amostra),
            )
            return Sucesso(
                TabelaExtraida(
                    nome_tabela=tabela,
                    nome_escopo=escopo,
                    colunas=colunas,
                    total_linhas=total_linhas,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                ),
                avisos=avisos,
            )
        finally:
            conexao.close()

"""Extrator concreto para bancos MariaDB."""

import threading
from typing import NamedTuple, assert_never

import polars as pl
import pymysql
from dbutils.pooled_db import PooledDB

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.construir_metadados_de_amostra import (
    construir_metadados_de_amostra,
)
from ddf.infrastructure.adapters.extractors.mariadb.mapeamento_de_tipos import (
    _extrair_coluna_json_valid,
    mapear_tipo_mariadb,
)
from ddf.infrastructure.adapters.extractors.seed_efetivo import seed_efetivo

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
           numeric_precision, numeric_scale, is_nullable
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

# AND kcu.table_name = %s nos dois lados do JOIN: nomes de constraint no
# MariaDB são escopados por TABELA, não por schema — duas tabelas do mesmo
# schema podem ter uma UNIQUE KEY com nome idêntico (ex.: "email" gerado por
# UNIQUE(email) em tabelas diferentes). Sem esse filtro, o JOIN por
# constraint_name+table_schema cruza linhas de tabelas diferentes e classifica
# colunas UNIQUE reais como não-únicas por acidente (validado empiricamente
# contra MariaDB 11 real durante a revisão desta issue).
_COLUNAS_UNICAS_SQL = """
    SELECT kcu.constraint_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
        AND tc.table_name = kcu.table_name
    WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s AND tc.table_name = %s
"""
# `_construir_coluna` só aceita um match de `_extrair_coluna_json_valid`
# se o nome extraído também existir entre as colunas reais desta tabela
# (`linhas_colunas`) — a validação cruzada é o que torna este SELECT sem
# filtro de tabela seguro de usar.
_COLUNAS_JSON_SQL = """
    SELECT cc.check_clause
    FROM information_schema.table_constraints tc
    JOIN information_schema.check_constraints cc
        ON tc.constraint_schema = cc.constraint_schema
        AND tc.constraint_name = cc.constraint_name
    WHERE tc.constraint_type = 'CHECK'
        AND tc.table_schema = %s AND tc.table_name = %s
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
    is_nullable: str


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
    colunas_unicas: set[str],
    colunas_json: set[str],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK/UNIQUE/JSON já lidas.

    `colunas_json` sobrescreve o resultado de `mapear_tipo_mariadb` — o
    MariaDB nunca reporta `data_type == "json"` de verdade (ver
    `_extrair_coluna_json_valid`), então a única forma de saber que uma
    coluna `LONGTEXT` é na real uma coluna `JSON` é via essa reclassificação
    baseada no `CHECK_CLAUSE`, não via `data_type`.
    """
    referencia = colunas_fk.get(linha.nome)
    tipo_dado = (
        TipoDeDado(categoria=CategoriaDeDado.JSON)
        if linha.nome in colunas_json
        else mapear_tipo_mariadb(
            linha.data_type,
            linha.column_type,
            linha.tamanho_maximo,
            linha.precisao,
            linha.escala,
        )
    )
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=tipo_dado,
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=referencia is not None,
        referencia=referencia,
        nao_nulavel=linha.is_nullable == "NO",
        unica=linha.nome in colunas_unicas,
    )


def _colunas_unicas_de_coluna_unica(
    linhas: list[tuple[str, str]],
) -> set[str]:
    """Agrupa (constraint_name, column_name) e mantém só constraints de 1 coluna.

    Uma constraint UNIQUE composta (2+ colunas) não torna nenhuma coluna
    individual única sozinha — só constraints com exatamente 1 linha no grupo
    (uma única coluna membro) contam.

    Args:
        linhas: pares (constraint_name, column_name) de _COLUNAS_UNICAS_SQL.

    Returns:
        Nomes de coluna que são a única membro de sua constraint UNIQUE.
    """
    colunas_por_constraint: dict[str, list[str]] = {}
    for nome_constraint, nome_coluna in linhas:
        colunas_por_constraint.setdefault(nome_constraint, []).append(nome_coluna)
    return {
        colunas[0]
        for colunas in colunas_por_constraint.values()
        if len(colunas) == 1
    }


def _colunas_json_de_check_clauses(
    check_clauses: list[str], nomes_colunas_reais: set[str]
) -> set[str]:
    """Extrai as colunas JSON reais a partir dos CHECK_CLAUSE da tabela.

    `_COLUNAS_JSON_SQL` pode retornar CHECK_CLAUSE de constraints de outra
    tabela do schema com o mesmo nome (ver comentário da query — MariaDB
    escopa nome de constraint por tabela, não por schema, e
    CHECK_CONSTRAINTS não tem TABLE_NAME pra filtrar isso na query). O
    cruzamento com `nomes_colunas_reais` (as colunas de fato lidas de
    `information_schema.columns` para esta tabela) é o que descarta esse
    ruído — um nome extraído que não é coluna desta tabela é ignorado.

    Args:
        check_clauses: valores de CHECK_CLAUSE retornados por
            _COLUNAS_JSON_SQL para o par (escopo, tabela) já filtrado.
        nomes_colunas_reais: nomes de todas as colunas desta tabela, lidas
            de _COLUNAS_SQL.

    Returns:
        Nomes de coluna desta tabela que são JSON de verdade.
    """
    colunas_json: set[str] = set()
    for check_clause in check_clauses:
        nome_coluna = _extrair_coluna_json_valid(check_clause)
        if nome_coluna is not None and nome_coluna in nomes_colunas_reais:
            colunas_json.add(nome_coluna)
    return colunas_json


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

                cursor.execute(_COLUNAS_UNICAS_SQL, (escopo, tabela))
                colunas_unicas = _colunas_unicas_de_coluna_unica(cursor.fetchall())

                cursor.execute(_COLUNAS_JSON_SQL, (escopo, tabela))
                nomes_colunas_reais = {linha.nome for linha in linhas_colunas}
                colunas_json = _colunas_json_de_check_clauses(
                    [check_clause for (check_clause,) in cursor.fetchall()],
                    nomes_colunas_reais,
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
                        _construir_coluna(
                            linha_coluna,
                            colunas_pk,
                            colunas_fk,
                            colunas_unicas,
                            colunas_json,
                        )
                    )

                cursor.execute(_TOTAL_LINHAS_SQL, (escopo, tabela))
                linha_total = cursor.fetchone()
                total_linhas = (
                    max(0, round(linha_total[0]))
                    if linha_total and linha_total[0] is not None
                    else 0
                )

                requisicao = self._configuracao.estrategia.requisicao
                requisicao_efetiva: RequisicaoDeAmostragem
                identificador_tabela = (
                    f"{_quotar_identificador(escopo)}.{_quotar_identificador(tabela)}"
                )
                match requisicao:
                    case AmostragemProbabilistica(percentual=percentual, seed=seed):
                        seed_usado = seed_efetivo(seed)
                        requisicao_efetiva = AmostragemProbabilistica(
                            percentual=percentual, seed=seed_usado
                        )
                        consulta_amostra = (
                            f"SELECT * FROM {identificador_tabela} "
                            "WHERE RAND(%s) <= %s"
                        )
                        cursor.execute(
                            consulta_amostra, (seed_usado, percentual / 100)
                        )
                    case AmostragemIntegral():
                        requisicao_efetiva = requisicao
                        cursor.execute(f"SELECT * FROM {identificador_tabela}")
                    case _ as nunca:
                        assert_never(nunca)

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

            match requisicao_efetiva:
                case AmostragemIntegral():
                    total_linhas_final = len(amostra)
                case AmostragemProbabilistica():
                    total_linhas_final = total_linhas
                case _ as nunca:
                    assert_never(nunca)

            metadados_amostra, avisos_amostra = construir_metadados_de_amostra(
                nome=self._configuracao.estrategia.nome,
                requisicao=requisicao_efetiva,
                tamanho_amostra=len(amostra),
                total_linhas=total_linhas_final,
                origem="ExtratorMariaDB",
                causa_provavel="sem ANALYZE TABLE recente",
            )
            avisos.extend(avisos_amostra)
            return Sucesso(
                TabelaExtraida(
                    nome_tabela=tabela,
                    nome_escopo=escopo,
                    colunas=colunas,
                    total_linhas=total_linhas_final,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                ),
                avisos=avisos,
            )
        finally:
            conexao.close()

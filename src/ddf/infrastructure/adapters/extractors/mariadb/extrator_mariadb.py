"""Extrator concreto para bancos MariaDB."""

import threading
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, NamedTuple, assert_never

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
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.comum.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.comum.construir_metadados_de_amostra import (  # noqa: E501
    construir_metadados_de_amostra,
)
from ddf.infrastructure.adapters.extractors.comum.construir_restricoes_fk_compostas import (  # noqa: E501
    construir_restricoes_fk_compostas,
)
from ddf.infrastructure.adapters.extractors.comum.seed_efetivo import seed_efetivo
from ddf.infrastructure.adapters.extractors.mariadb._queries import (
    _CHAVES_ESTRANGEIRAS_SQL,
    _CHAVES_PRIMARIAS_SQL,
    _COLUNAS_JSON_SQL,
    _COLUNAS_SQL,
    _COLUNAS_UNICAS_SQL,
    _LISTAR_ESCOPOS_SQL,
    _LISTAR_TABELAS_SQL,
    _TOTAL_LINHAS_SQL,
)
from ddf.infrastructure.adapters.extractors.mariadb.mapeamento_de_tipos import (
    _extrair_coluna_json_valid,
    mapear_tipo_mariadb,
)


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SQL (a partir da 2ª coluna — a 1ª é table_name, usada só para
    agrupar por tabela antes de construir esta tupla) — construir a tupla
    é o único ponto onde essa correspondência posicional existe; daqui pra
    frente, todo o código lê por nome (`linha.data_type`), não por índice.
    """

    nome: str
    data_type: str
    column_type: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None
    is_nullable: str


class _MetadadosDoSchema(NamedTuple):
    """Metadados de catálogo de todas as tabelas de um escopo, lidos de uma vez.

    Populado por ExtratorMariaDB._obter_metadados_schema e cacheado por
    escopo — elimina o N+1 de rodar 6 queries de metadado por tabela
    restrita. Sem restricoes_fk_compostas_por_tabela (diferente do
    _MetadadosDoSchema equivalente do ExtratorPostgres): construir_
    restricoes_fk_compostas é função pura de CPU, não bate no banco —
    extrair_tabela a reconstrói por tabela a partir de fks_por_tabela já
    cacheado, sem custo de round-trip extra.
    """

    colunas_por_tabela: dict[str, list[_LinhaColuna]]
    pks_por_tabela: dict[str, set[str]]
    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]]
    unicas_por_tabela: dict[str, set[str]]
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]]
    colunas_json_por_tabela: dict[str, set[str]]
    total_linhas_por_tabela: dict[str, int]


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


def _particionar_colunas_unicas(
    linhas: list[tuple[str, str]],
) -> tuple[set[str], list[RestricaoUnica]]:
    """Agrupa (constraint_name, column_name) por constraint e particiona por tamanho.

    Constraint com 1 coluna vira `unica` single-column; com 2+ colunas vira
    uma `RestricaoUnica` composta. Assume que `linhas` já pertence a uma
    única tabela — quem chama (`_agrupar_colunas_unicas_por_tabela`)
    garante isso agrupando por `table_name` antes.

    Args:
        linhas: pares (constraint_name, column_name) de uma única tabela,
            já ordenados por `(constraint_name, ordinal_position)` pela
            query, preservando a ordem real das colunas dentro da
            constraint.

    Returns:
        Tupla (nomes de coluna únicas single-column, lista de RestricaoUnica
        para as constraints compostas).
    """
    colunas_por_constraint: dict[str, list[str]] = {}
    for nome_constraint, nome_coluna in linhas:
        colunas_por_constraint.setdefault(nome_constraint, []).append(nome_coluna)

    unicas: set[str] = set()
    restricoes_unicas: list[RestricaoUnica] = []
    for colunas in colunas_por_constraint.values():
        if len(colunas) == 1:
            unicas.add(colunas[0])
        else:
            restricoes_unicas.append(RestricaoUnica(colunas=tuple(colunas)))
    return unicas, restricoes_unicas


def _agrupar_colunas_unicas_por_tabela(
    linhas: list[tuple[str, str, str]],
) -> tuple[dict[str, set[str]], dict[str, list[RestricaoUnica]]]:
    """Separa por tabela antes de particionar — constraint só é única por tabela.

    `_COLUNAS_UNICAS_SQL` já cruza `table_name` no JOIN (não só no WHERE),
    então linhas de tabelas diferentes nunca se misturam ali; mas duas
    tabelas do mesmo escopo podem usar o mesmo `constraint_name` (ex.:
    `UNIQUE(email)` gerando "email" em ambas) — sem separar por tabela
    antes de chamar `_particionar_colunas_unicas`, os grupos colidiriam
    entre tabelas.

    Args:
        linhas: (table_name, constraint_name, column_name) de todo o
            escopo.

    Returns:
        (unicas_por_tabela, restricoes_unicas_por_tabela).
    """
    linhas_por_tabela: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for nome_tabela, nome_constraint, nome_coluna in linhas:
        linhas_por_tabela[nome_tabela].append((nome_constraint, nome_coluna))

    unicas_por_tabela: dict[str, set[str]] = {}
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]] = {}
    for nome_tabela, linhas_da_tabela in linhas_por_tabela.items():
        unicas, restricoes = _particionar_colunas_unicas(linhas_da_tabela)
        unicas_por_tabela[nome_tabela] = unicas
        restricoes_unicas_por_tabela[nome_tabela] = restricoes
    return unicas_por_tabela, restricoes_unicas_por_tabela


def _colunas_json_de_check_clauses(
    check_clauses: list[str], nomes_colunas_reais: set[str]
) -> set[str]:
    """Extrai as colunas JSON reais a partir dos CHECK_CLAUSE de uma tabela.

    O cruzamento com `nomes_colunas_reais` (as colunas de fato lidas de
    `information_schema.columns` para esta tabela) é defesa em profundidade
    contra CHECK_CLAUSE que não segue o padrão `json_valid(...)`.

    Args:
        check_clauses: valores de CHECK_CLAUSE de uma única tabela, já
            separados por `_agrupar_colunas_json_por_tabela`.
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


def _agrupar_colunas_json_por_tabela(
    linhas: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Agrupa (table_name, check_clause) de todo o escopo por tabela.

    `information_schema.check_constraints` traz `table_name` nativamente —
    diferente de UNIQUE, aqui não há JOIN nenhum pra cruzar, só agrupamento
    direto pela coluna que a própria view já expõe.

    Args:
        linhas: (table_name, check_clause) de todo o escopo.

    Returns:
        check_clauses agrupados por table_name.
    """
    check_clauses_por_tabela: dict[str, list[str]] = defaultdict(list)
    for nome_tabela, check_clause in linhas:
        check_clauses_por_tabela[nome_tabela].append(check_clause)
    return dict(check_clauses_por_tabela)


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
        connect_timeout: int = 10,
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
            connect_timeout: segundos até desistir de abrir a conexão TCP
                inicial. Declarado explicitamente pelo mesmo motivo do
                `connect_timeout` de `ExtratorPostgres` (host inacessível
                não pode travar indefinidamente) — o valor já era o default
                do `pymysql`, então isso não muda o comportamento atual, só
                deixa de depender implicitamente do driver.

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
        self._connect_timeout = connect_timeout
        self._pool: PooledDB | None = None
        self._lock_pool = threading.Lock()
        self._cache_schemas: dict[str, _MetadadosDoSchema] = {}
        self._lock_cache_schemas = threading.Lock()

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
                            connect_timeout=self._connect_timeout,
                        )
                    except pymysql.err.OperationalError as erro:
                        return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    @contextmanager
    def _conexao(self) -> Generator[Resultado[Any], None, None]:
        """Empresta uma conexão do pool, com devolução (`close`) garantida.

        Sem semáforo próprio — diferente do `ExtratorPostgres`, o `PooledDB`
        já foi criado com `blocking=True` (`_obter_pool`), então
        `pool.connection()` bloqueia internamente quando o pool está
        saturado, em vez de levantar erro como o `ThreadedConnectionPool`
        do psycopg2 faria.

        `yield`a um `Falha` cedo, sem entrar no `try`/`finally` de conexão,
        quando o pool não pode ser obtido ou `pool.connection()` falha —
        nesses casos não há conexão a devolver. Tipo `Any` porque
        `dbutils.pooled_db` não tem stubs (`ignore_missing_imports` em
        `pyproject.toml`).
        """
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            yield resultado_pool
            return
        pool = resultado_pool.valor
        try:
            conexao = pool.connection()
        except pymysql.err.OperationalError as erro:
            yield Falha(f"Não foi possível conectar: {erro}")
            return
        try:
            yield Sucesso(conexao)
        finally:
            conexao.close()

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (databases) disponíveis, ordenados por nome."""
        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_ESCOPOS_SQL)
                escopos: list[str] = []
                for linha_escopo in cursor.fetchall():
                    nome_escopo = linha_escopo[0]
                    escopos.append(nome_escopo)
            return Sucesso(escopos)

    def listar_tabelas(self, escopo: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (escopo, nome_tabela) do escopo informado, ordenado por nome_tabela."""
        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_TABELAS_SQL, (escopo,))
                tabelas: list[tuple[str, str]] = []
                for linha_tabela in cursor.fetchall():
                    nome_escopo, nome_tabela = linha_tabela
                    tabelas.append((nome_escopo, nome_tabela))
            return Sucesso(tabelas)

    def _obter_metadados_schema(self, escopo: str) -> Resultado[_MetadadosDoSchema]:
        """Cacheia os metadados de catálogo de um escopo inteiro, por escopo.

        Populado sob demanda na 1ª extrair_tabela daquele escopo — chamadas
        seguintes (mesmo escopo, tabelas diferentes) reaproveitam o cache em
        vez de repetir os 6 round-trips de metadado por tabela.
        Double-checked locking, mesmo padrão de _obter_pool/_lock_pool: um
        único lock para todo o cache (não um lock por escopo) — populações
        de escopos diferentes se serializam entre si, mas isso só acontece
        uma vez por escopo ao longo da vida do Extrator, nunca por tabela.
        """
        metadados = self._cache_schemas.get(escopo)
        if metadados is not None:
            return Sucesso(metadados)
        with self._lock_cache_schemas:
            metadados = self._cache_schemas.get(escopo)
            if metadados is not None:
                return Sucesso(metadados)

            with self._conexao() as resultado_conexao:
                if isinstance(resultado_conexao, Falha):
                    return resultado_conexao
                conexao = resultado_conexao.valor
                with conexao.cursor() as cursor:
                    cursor.execute(_COLUNAS_SQL, (escopo,))
                    colunas_por_tabela: dict[str, list[_LinhaColuna]] = defaultdict(
                        list
                    )
                    for linha_bruta in cursor.fetchall():
                        nome_tabela, *resto_colunas = linha_bruta
                        colunas_por_tabela[nome_tabela].append(
                            _LinhaColuna(*resto_colunas)
                        )

                    cursor.execute(_CHAVES_PRIMARIAS_SQL, (escopo,))
                    pks_por_tabela: dict[str, set[str]] = defaultdict(set)
                    for nome_tabela, nome_coluna_pk in cursor.fetchall():
                        pks_por_tabela[nome_tabela].add(nome_coluna_pk)

                    cursor.execute(_CHAVES_ESTRANGEIRAS_SQL, (escopo,))
                    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]] = (
                        defaultdict(list)
                    )
                    for linha_fk in cursor.fetchall():
                        nome_tabela, *resto_fk = linha_fk
                        fks_por_tabela[nome_tabela].append(tuple(resto_fk))

                    cursor.execute(_COLUNAS_UNICAS_SQL, (escopo,))
                    unicas_por_tabela, restricoes_unicas_por_tabela = (
                        _agrupar_colunas_unicas_por_tabela(list(cursor.fetchall()))
                    )

                    cursor.execute(_COLUNAS_JSON_SQL, (escopo,))
                    check_clauses_por_tabela = _agrupar_colunas_json_por_tabela(
                        list(cursor.fetchall())
                    )
                    colunas_json_por_tabela: dict[str, set[str]] = {}
                    for nome_tabela, linhas_colunas in colunas_por_tabela.items():
                        nomes_colunas_reais = {linha.nome for linha in linhas_colunas}
                        colunas_json_por_tabela[nome_tabela] = (
                            _colunas_json_de_check_clauses(
                                check_clauses_por_tabela.get(nome_tabela, []),
                                nomes_colunas_reais,
                            )
                        )

                    cursor.execute(_TOTAL_LINHAS_SQL, (escopo,))
                    total_linhas_por_tabela: dict[str, int] = {}
                    for nome_tabela, linhas_estimadas in cursor.fetchall():
                        total_linhas_por_tabela[nome_tabela] = (
                            max(0, round(linhas_estimadas))
                            if linhas_estimadas is not None
                            else 0
                        )

            metadados = _MetadadosDoSchema(
                colunas_por_tabela=dict(colunas_por_tabela),
                pks_por_tabela=dict(pks_por_tabela),
                fks_por_tabela=dict(fks_por_tabela),
                unicas_por_tabela=unicas_por_tabela,
                restricoes_unicas_por_tabela=restricoes_unicas_por_tabela,
                colunas_json_por_tabela=colunas_json_por_tabela,
                total_linhas_por_tabela=total_linhas_por_tabela,
            )
            self._cache_schemas[escopo] = metadados
            return Sucesso(metadados)

    def extrair_tabela(self, escopo: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_estrategia = self._configuracao.estrategia_obrigatoria()
        if isinstance(resultado_estrategia, Falha):
            return resultado_estrategia
        estrategia = resultado_estrategia.valor

        resultado_metadados = self._obter_metadados_schema(escopo)
        if isinstance(resultado_metadados, Falha):
            return resultado_metadados
        metadados = resultado_metadados.valor

        linhas_colunas = metadados.colunas_por_tabela.get(tabela)
        if not linhas_colunas:
            return Falha(f"Schema '{escopo}' ou tabela '{tabela}' não encontrada.")

        colunas_pk = metadados.pks_por_tabela.get(tabela, set())
        linhas_fk = metadados.fks_por_tabela.get(tabela, [])
        linhas_fk_por_coluna: list[tuple[str, str, str, str]] = []
        for nome_coluna, escopo_ref, tabela_ref, coluna_ref, _ in linhas_fk:
            linhas_fk_por_coluna.append(
                (nome_coluna, escopo_ref, tabela_ref, coluna_ref)
            )
        colunas_fk, avisos = construir_colunas_fk(
            linhas_fk_por_coluna, origem="ExtratorMariaDB"
        )
        restricoes_fk_compostas = construir_restricoes_fk_compostas(linhas_fk)

        colunas_unicas = metadados.unicas_por_tabela.get(tabela, set())
        restricoes_unicas = metadados.restricoes_unicas_por_tabela.get(tabela, [])
        colunas_json = metadados.colunas_json_por_tabela.get(tabela, set())
        total_linhas = metadados.total_linhas_por_tabela.get(tabela, 0)

        # Colunas só são finalizadas depois da amostra (abaixo) — ao
        # contrário do ExtratorPostgres, aqui a promoção de BOOLEAN
        # depende de dado real já carregado. Ver docstring de
        # _promover_booleanos_pela_amostra.
        candidatos_booleanos: set[str] = set()
        colunas: list[ColunaExtraida] = []
        for linha_coluna in linhas_colunas:
            # startswith, não == : cobre "tinyint(1) unsigned" além de
            # "tinyint(1)" — COLUMN_TYPE inclui o modificador unsigned
            # quando presente, e um tinyint(1) unsigned também é candidato
            # legítimo a BOOLEAN.
            if linha_coluna.column_type.startswith("tinyint(1)"):
                candidatos_booleanos.add(linha_coluna.nome)
            colunas.append(
                _construir_coluna(
                    linha_coluna, colunas_pk, colunas_fk, colunas_unicas, colunas_json
                )
            )

        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                requisicao = estrategia.requisicao
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
                            f"SELECT * FROM {identificador_tabela} WHERE RAND(%s) <= %s"
                        )
                        cursor.execute(consulta_amostra, (seed_usado, percentual / 100))
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
                nome=estrategia.nome,
                requisicao=requisicao_efetiva,
                tamanho_amostra=len(amostra),
                total_linhas=total_linhas_final,
                origem="ExtratorMariaDB",
                causa_provavel="sem ANALYZE TABLE recente",
                identificador_tabela=f"{escopo}.{tabela}",
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
                    restricoes_unicas=restricoes_unicas,
                    restricoes_fk_compostas=restricoes_fk_compostas,
                ),
                avisos=avisos,
            )

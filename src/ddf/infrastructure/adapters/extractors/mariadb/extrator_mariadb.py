"""Extrator concreto para bancos MariaDB."""

import threading
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, assert_never

import polars as pl
import pymysql
from dbutils.pooled_db import PooledDB

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
    RequisicaoPorFaixa,
)
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.aviso import Aviso
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
from ddf.infrastructure.adapters.extractors.mariadb._construcao import (
    _agrupar_colunas_json_por_tabela,
    _agrupar_colunas_unicas_por_tabela,
    _colunas_json_de_check_clauses,
    _construir_coluna,
    _elegibilidade_de_pk_para_faixa,
    _LinhaColuna,
    _MetadadosDoSchema,
    _PkElegivel,
    _PkNaoElegivel,
    _promover_booleanos_pela_amostra,
    _quotar_identificador,
)
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

# Nº de faixas contíguas sorteadas independentemente em RequisicaoPorFaixa —
# aproxima o comportamento de blocos espalhados do TABLESAMPLE SYSTEM do
# Postgres sem exigir uma consulta por linha amostrada (inviável em lote).
# Candidato inicial, calibrado pelo benchmark da issue #114 — não um valor
# definitivo.
_K_FAIXAS = 10


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

                    restricoes_fk_compostas_por_tabela: dict[
                        str, list[RestricaoDeFkComposta]
                    ] = {
                        nome_tabela: construir_restricoes_fk_compostas(linhas)
                        for nome_tabela, linhas in fks_por_tabela.items()
                    }

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
                restricoes_fk_compostas_por_tabela=restricoes_fk_compostas_por_tabela,
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
        colunas_fk = construir_colunas_fk(linhas_fk_por_coluna)
        avisos: list[Aviso] = []
        restricoes_fk_compostas = metadados.restricoes_fk_compostas_por_tabela.get(
            tabela, []
        )

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
                n_pedido_por_faixa: int | None = None
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
                    case RequisicaoPorFaixa(percentual=percentual, seed=seed):
                        seed_usado = seed_efetivo(seed)
                        elegibilidade = _elegibilidade_de_pk_para_faixa(
                            colunas_pk, linhas_colunas
                        )
                        match elegibilidade:
                            case _PkElegivel(nome_coluna=nome_pk):
                                requisicao_efetiva = RequisicaoPorFaixa(
                                    percentual=percentual, seed=seed_usado
                                )
                                identificador_pk = _quotar_identificador(nome_pk)
                                cursor.execute(
                                    f"SELECT MAX({identificador_pk}) "
                                    f"FROM {identificador_tabela}"
                                )
                                linha_max = cursor.fetchone()
                                max_pk = linha_max[0] if linha_max else None
                                n_pedido_por_faixa = max(
                                    1, round(total_linhas * percentual / 100)
                                )
                                linhas_por_faixa = max(
                                    1, n_pedido_por_faixa // _K_FAIXAS
                                )
                                subconsultas: list[str] = []
                                parametros: list[object] = []
                                for indice_faixa in range(_K_FAIXAS):
                                    seed_da_faixa = seed_usado + indice_faixa
                                    subconsultas.append(
                                        f"(SELECT * FROM {identificador_tabela} "
                                        f"WHERE {identificador_pk} >= "
                                        f"FLOOR(RAND(%s) * %s) "
                                        f"ORDER BY {identificador_pk} LIMIT %s)"
                                    )
                                    parametros.extend(
                                        [seed_da_faixa, max_pk, linhas_por_faixa]
                                    )
                                consulta_amostra = " UNION ALL ".join(subconsultas)
                                cursor.execute(consulta_amostra, tuple(parametros))
                            case _PkNaoElegivel(motivo=motivo):
                                requisicao_efetiva = AmostragemProbabilistica(
                                    percentual=percentual, seed=seed_usado
                                )
                                avisos.append(
                                    Aviso(
                                        mensagem=(
                                            f"'{identificador_tabela}': amostragem "
                                            "por faixa caiu para o mecanismo "
                                            f"probabilístico padrão ({motivo}) — "
                                            "sem chave primária de coluna única e "
                                            "tipo inteiro, não há como cortar a "
                                            "tabela em faixas contíguas."
                                        ),
                                        origem="ExtratorMariaDB",
                                    )
                                )
                                consulta_amostra = (
                                    f"SELECT * FROM {identificador_tabela} "
                                    "WHERE RAND(%s) <= %s"
                                )
                                cursor.execute(
                                    consulta_amostra, (seed_usado, percentual / 100)
                                )
                            case _ as nunca_elegibilidade:
                                assert_never(nunca_elegibilidade)
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

                if (
                    n_pedido_por_faixa is not None
                    and len(amostra) < 0.5 * n_pedido_por_faixa
                ):
                    avisos.append(
                        Aviso(
                            mensagem=(
                                f"'{identificador_tabela}': amostra por faixa "
                                f"trouxe {len(amostra)} linhas, bem menos que as "
                                f"{n_pedido_por_faixa} pedidas — sintoma de gaps "
                                "densos na chave primária logo após os pontos "
                                "sorteados."
                            ),
                            origem="ExtratorMariaDB",
                        )
                    )

                colunas = _promover_booleanos_pela_amostra(
                    colunas, amostra, candidatos_booleanos
                )

            match requisicao_efetiva:
                case AmostragemIntegral():
                    total_linhas_final = len(amostra)
                case AmostragemProbabilistica() | RequisicaoPorFaixa():
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
                descricao_vies_por_faixa=(
                    f"amostragem por {_K_FAIXAS} faixas contíguas de chave "
                    "primária, não por bloco físico de disco — pode "
                    "distorcer percentual_nulo/percentual_unico/"
                    "valores_frequentes em tabelas com padrão de inserção "
                    "em lote. Uma amostra verdadeiramente aleatória por PK "
                    "exigiria uma consulta por linha amostrada, custo "
                    "inviável em lote."
                ),
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

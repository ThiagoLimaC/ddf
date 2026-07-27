"""Extrator concreto para bancos Postgres."""

import threading
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from typing import NamedTuple, assert_never

import polars as pl
from psycopg2 import OperationalError, sql
from psycopg2.extensions import connection as conexao_postgres
from psycopg2.pool import ThreadedConnectionPool

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
)
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.construir_metadados_de_amostra import (
    construir_metadados_de_amostra,
)
from ddf.infrastructure.adapters.extractors.postgres._queries import (
    _CHAVES_ESTRANGEIRAS_SCHEMA_SQL,
    _CHAVES_PRIMARIAS_SCHEMA_SQL,
    _COLUNAS_SCHEMA_SQL,
    _COLUNAS_UNICAS_SCHEMA_SQL,
    _LISTAR_ESCOPOS_SQL,
    _LISTAR_TABELAS_SQL,
    _TOTAL_LINHAS_SCHEMA_SQL,
)
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)
from ddf.infrastructure.adapters.extractors.seed_efetivo import seed_efetivo


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SCHEMA_SQL (a partir da 2ª coluna — a 1ª é table_name, usada só
    para agrupar por tabela antes de construir esta tupla) — construir a
    tupla é o único ponto onde essa correspondência posicional existe; daqui
    pra frente, todo o código lê por nome (`linha.udt_name`), não por índice.
    """

    nome: str
    udt_name: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None
    is_nullable: str


class _MetadadosDoSchema(NamedTuple):
    """Metadados de catálogo de todas as tabelas de um schema, lidos de uma vez.

    Populado por ExtratorPostgres._obter_metadados_schema e cacheado por
    schema — elimina o N+1 de rodar 4 queries de metadado por tabela restrita.
    fks_por_tabela guarda linhas cruas (mesmo formato que
    construir_colunas_fk espera), não ReferenciaDeColuna já resolvida — a
    resolução (com Aviso de colisão) continua acontecendo por tabela, em
    extrair_tabela, não aqui.
    """

    colunas_por_tabela: dict[str, list[_LinhaColuna]]
    pks_por_tabela: dict[str, set[str]]
    fks_por_tabela: dict[str, list[tuple[str, str, str, str]]]
    unicas_por_tabela: dict[str, set[str]]
    total_linhas_por_tabela: dict[str, int]


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
        self._cache_schemas: dict[str, _MetadadosDoSchema] = {}
        self._lock_cache_schemas = threading.Lock()

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

    @contextmanager
    def _conexao(self) -> Generator[Resultado[conexao_postgres], None, None]:
        """Empresta uma conexão do pool, sob o semáforo, com release garantido.

        `yield`a um `Falha` cedo, sem entrar no bloco `try`/`finally` de
        conexão, quando o próprio pool não pode ser obtido ou o
        `getconn()` falha — nesses casos não há conexão nem posse do
        semáforo a devolver. Quando a conexão é obtida com sucesso, o
        `finally` garante `putconn` + liberação do semáforo mesmo se o
        corpo do `with` levantar uma exceção não tratada.
        """
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            yield resultado_pool
            return
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            self._semaforo.release()
            yield Falha(f"Não foi possível conectar: {erro}")
            return
        try:
            conexao.autocommit = True
            yield Sucesso(conexao)
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (schemas) disponíveis, ordenados por nome."""
        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_ESCOPOS_SQL)
                escopos: list[str] = []
                for linha_escopo in cursor.fetchall():
                    nome_schema = linha_escopo[0]
                    escopos.append(nome_schema)
            return Sucesso(escopos)

    def listar_tabelas(self, schema: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (schema, nome_tabela) do schema informado, ordenado por nome_tabela."""
        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(_LISTAR_TABELAS_SQL, (schema,))
                tabelas: list[tuple[str, str]] = []
                for linha_tabela in cursor.fetchall():
                    nome_schema, nome_tabela = linha_tabela
                    tabelas.append((nome_schema, nome_tabela))
            return Sucesso(tabelas)

    def _obter_metadados_schema(self, schema: str) -> Resultado[_MetadadosDoSchema]:
        """Cacheia os metadados de catálogo de um schema inteiro, por schema.

        Populado sob demanda na 1ª extrair_tabela daquele schema — chamadas
        seguintes (mesmo schema, tabelas diferentes) reaproveitam o cache em
        vez de repetir os 4 round-trips de metadado por tabela.
        Double-checked locking, mesmo padrão de _obter_pool/_lock_pool: um
        único lock para todo o cache (não um lock por schema) — populações
        de schemas diferentes se serializam entre si, mas isso só acontece
        uma vez por schema ao longo da vida do Extrator, nunca por tabela.
        """
        metadados = self._cache_schemas.get(schema)
        if metadados is not None:
            return Sucesso(metadados)
        with self._lock_cache_schemas:
            metadados = self._cache_schemas.get(schema)
            if metadados is not None:
                return Sucesso(metadados)

            with self._conexao() as resultado_conexao:
                if isinstance(resultado_conexao, Falha):
                    return resultado_conexao
                conexao = resultado_conexao.valor
                with conexao.cursor() as cursor:
                    cursor.execute(_COLUNAS_SCHEMA_SQL, (schema,))
                    colunas_por_tabela: dict[str, list[_LinhaColuna]] = defaultdict(
                        list
                    )
                    for linha_bruta in cursor.fetchall():
                        nome_tabela, *resto_colunas = linha_bruta
                        colunas_por_tabela[nome_tabela].append(
                            _LinhaColuna(*resto_colunas)
                        )

                    cursor.execute(_CHAVES_PRIMARIAS_SCHEMA_SQL, (schema,))
                    pks_por_tabela: dict[str, set[str]] = defaultdict(set)
                    for nome_tabela, nome_coluna_pk in cursor.fetchall():
                        pks_por_tabela[nome_tabela].add(nome_coluna_pk)

                    cursor.execute(_CHAVES_ESTRANGEIRAS_SCHEMA_SQL, (schema,))
                    fks_por_tabela: dict[str, list[tuple[str, str, str, str]]] = (
                        defaultdict(list)
                    )
                    for linha_fk in cursor.fetchall():
                        nome_tabela, *resto_fk = linha_fk
                        fks_por_tabela[nome_tabela].append(tuple(resto_fk))

                    cursor.execute(_COLUNAS_UNICAS_SCHEMA_SQL, (schema,))
                    unicas_por_tabela: dict[str, set[str]] = defaultdict(set)
                    for nome_tabela, nome_coluna_unica in cursor.fetchall():
                        unicas_por_tabela[nome_tabela].add(nome_coluna_unica)

                    cursor.execute(_TOTAL_LINHAS_SCHEMA_SQL, (schema,))
                    total_linhas_por_tabela: dict[str, int] = {}
                    for nome_tabela, linhas_estimadas in cursor.fetchall():
                        total_linhas_por_tabela[nome_tabela] = max(
                            0, round(linhas_estimadas)
                        )

            metadados = _MetadadosDoSchema(
                colunas_por_tabela=dict(colunas_por_tabela),
                pks_por_tabela=dict(pks_por_tabela),
                fks_por_tabela=dict(fks_por_tabela),
                unicas_por_tabela=dict(unicas_por_tabela),
                total_linhas_por_tabela=total_linhas_por_tabela,
            )
            self._cache_schemas[schema] = metadados
            return Sucesso(metadados)

    def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_metadados = self._obter_metadados_schema(schema)
        if isinstance(resultado_metadados, Falha):
            return resultado_metadados
        metadados = resultado_metadados.valor

        linhas_colunas = metadados.colunas_por_tabela.get(tabela)
        if not linhas_colunas:
            return Falha(f"Schema '{schema}' ou tabela '{tabela}' não encontrada.")

        colunas_pk = metadados.pks_por_tabela.get(tabela, set())
        colunas_fk, avisos = construir_colunas_fk(
            metadados.fks_por_tabela.get(tabela, []), origem="ExtratorPostgres"
        )
        colunas_unicas = metadados.unicas_por_tabela.get(tabela, set())
        total_linhas = metadados.total_linhas_por_tabela.get(tabela, 0)

        colunas: list[ColunaExtraida] = []
        for linha_coluna in linhas_colunas:
            colunas.append(
                _construir_coluna(linha_coluna, colunas_pk, colunas_fk, colunas_unicas)
            )

        requisicao = self._configuracao.estrategia.requisicao
        with self._conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                requisicao_efetiva: RequisicaoDeAmostragem
                match requisicao:
                    case AmostragemProbabilistica(percentual=percentual, seed=seed):
                        seed_usado = seed_efetivo(seed)
                        requisicao_efetiva = AmostragemProbabilistica(
                            percentual=percentual, seed=seed_usado
                        )
                        consulta_amostra = sql.SQL(
                            "SELECT * FROM {}.{} TABLESAMPLE BERNOULLI ({}) "
                            "REPEATABLE ({})"
                        ).format(
                            sql.Identifier(schema),
                            sql.Identifier(tabela),
                            sql.Literal(percentual),
                            sql.Literal(seed_usado),
                        )
                    case AmostragemIntegral():
                        requisicao_efetiva = requisicao
                        consulta_amostra = sql.SQL("SELECT * FROM {}.{}").format(
                            sql.Identifier(schema), sql.Identifier(tabela)
                        )
                    case _ as nunca:
                        assert_never(nunca)

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
                origem="ExtratorPostgres",
                causa_provavel="sem ANALYZE recente",
            )
            avisos.extend(avisos_amostra)
            return Sucesso(
                TabelaExtraida(
                    nome_tabela=tabela,
                    nome_escopo=schema,
                    colunas=colunas,
                    total_linhas=total_linhas_final,
                    amostra=amostra,
                    metadados_amostra=metadados_amostra,
                ),
                avisos=avisos,
            )

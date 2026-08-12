"""Extrator concreto para bancos Postgres."""

import logging
import threading
from collections import defaultdict
from typing import assert_never

import connectorx as cx
import polars as pl
from psycopg2 import sql
from psycopg2.extensions import connection as conexao_postgres

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
    RequisicaoPorFaixa,
)
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
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
from ddf.infrastructure.adapters.extractors.comum.leitura_paralela_intra_tabela import (  # noqa: E501
    deve_paralelizar_leitura,
)
from ddf.infrastructure.adapters.extractors.comum.ler_amostra_em_lotes import (
    LARGURA_MEDIA_PADRAO_BYTES,
    calcular_tamanho_lote,
    deve_usar_streaming,
    ler_amostra_em_lotes,
    ler_amostra_fetchall,
)
from ddf.infrastructure.adapters.extractors.comum.seed_efetivo import seed_efetivo
from ddf.infrastructure.adapters.extractors.postgres._conexoes import (
    TokenDeReserva,
    _GerenciadorDeConexoesPostgres,
)
from ddf.infrastructure.adapters.extractors.postgres._construcao import (
    _construir_coluna,
    _LinhaColuna,
    _MetadadosDoSchema,
    particoes_de_blocos,
)
from ddf.infrastructure.adapters.extractors.postgres._queries import (
    _CHAVES_ESTRANGEIRAS_SCHEMA_SQL,
    _CHAVES_PRIMARIAS_SCHEMA_SQL,
    _COLUNAS_COMPRIMIVEIS_SCHEMA_SQL,
    _COLUNAS_SCHEMA_SQL,
    _LARGURA_MEDIA_LINHA_SCHEMA_SQL,
    _LISTAR_ESCOPOS_SQL,
    _LISTAR_TABELAS_SQL,
    _RESTRICOES_UNICAS_SCHEMA_SQL,
    _TABELAS_PARTICIONADAS_SCHEMA_SQL,
    _TOTAL_BLOCOS_TABELA_SQL,
    _TOTAL_LINHAS_SCHEMA_SQL,
)

_logger = logging.getLogger(__name__)


# Linhas-alvo da sonda de largura real (TABLESAMPLE) — bounded pelo LIMIT,
# não pelo tamanho da tabela.
_LINHAS_AMOSTRA_LARGURA_REAL = 500


class ExtratorPostgres:
    """Extrai estrutura e amostra de tabelas de um banco Postgres."""

    def __init__(
        self,
        dsn: str,
        configuracao: ConfiguracaoDeExtracao,
        max_conexoes: int = 8,
        connect_timeout: int = 50,
        max_conexoes_por_tabela: int | None = None,
    ) -> None:
        """Guarda os parâmetros de conexão — o pool só é criado no primeiro uso.

        Args:
            dsn: string de conexão do Postgres.
            configuracao: política de amostragem, agnóstica de fonte.
            max_conexoes: nº máximo de conexões simultâneas que este Postgres
                aguenta com segurança — dimensiona o pool e o semáforo interno
                que impede o esgotamento do pool sob chamadas concorrentes.
            connect_timeout: segundos até desistir de abrir a conexão TCP
                inicial (parâmetro `connect_timeout` do libpq). Sem isso, um
                host inacessível por firewall (pacote descartado, não
                recusado) trava por um timeout de TCP do SO que pode passar
                de um minuto, antes de qualquer mensagem de erro aparecer.
            max_conexoes_por_tabela: teto de conexões que uma única tabela
                grande tenta reservar do mesmo semáforo pra ler em paralelo
                internamente. `None` (default) usa `min(4, max_conexoes)` —
                nunca excede o orçamento total, mesmo com `max_conexoes`
                pequeno (nesse caso a reserva simplesmente nunca atinge
                `MINIMO_CONEXOES_PARALELISMO` e a tabela cai no caminho
                sequencial, sem erro). Não exposto no wizard da CLI, mesmo
                tratamento de `max_conexoes`/`connect_timeout`.

        Raises:
            ValueError: se `max_conexoes` não for positivo, ou se
                `max_conexoes_por_tabela` for explicitado e não for
                positivo ou exceder `max_conexoes`.
        """
        if max_conexoes <= 0:
            raise ValueError(f"max_conexoes deve ser positivo ({max_conexoes}).")
        if max_conexoes_por_tabela is None:
            max_conexoes_por_tabela = min(4, max_conexoes)
        elif max_conexoes_por_tabela <= 0 or max_conexoes_por_tabela > max_conexoes:
            raise ValueError(
                "max_conexoes_por_tabela deve ser positivo e não exceder "
                f"max_conexoes ({max_conexoes_por_tabela} vs. {max_conexoes})."
            )
        # connectorx abre suas próprias conexões, fora do ThreadedConnectionPool
        # — connect_timeout só chega até elas se estiver embutido na DSN.
        # `dsn` já vem em formato URI (montada pelo wizard, `postgresql://...`,
        # com "?" opcional se já houver parâmetros extra do usuário).
        separador = "&" if "?" in dsn else "?"
        self._dsn_connectorx = f"{dsn}{separador}connect_timeout={connect_timeout}"
        self._configuracao = configuracao
        self._max_conexoes_por_tabela = max_conexoes_por_tabela
        self._conexoes = _GerenciadorDeConexoesPostgres(
            dsn, max_conexoes, connect_timeout
        )
        self._cache_schemas: dict[str, _MetadadosDoSchema] = {}
        self._lock_cache_schemas = threading.Lock()

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (schemas) disponíveis, ordenados por nome."""
        with self._conexoes.conexao() as resultado_conexao:
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
        with self._conexoes.conexao() as resultado_conexao:
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

            with self._conexoes.conexao() as resultado_conexao:
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

                    cursor.execute(_RESTRICOES_UNICAS_SCHEMA_SQL, (schema,))
                    grupos_unicos: dict[str, dict[int, list[str]]] = defaultdict(
                        lambda: defaultdict(list)
                    )
                    for nome_tabela, indexrelid, nome_coluna in cursor.fetchall():
                        grupos_unicos[nome_tabela][indexrelid].append(nome_coluna)

                    unicas_por_tabela: dict[str, set[str]] = defaultdict(set)
                    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]] = (
                        defaultdict(list)
                    )
                    for nome_tabela, indices in grupos_unicos.items():
                        for colunas_do_indice in indices.values():
                            if len(colunas_do_indice) == 1:
                                unicas_por_tabela[nome_tabela].add(colunas_do_indice[0])
                            else:
                                restricoes_unicas_por_tabela[nome_tabela].append(
                                    RestricaoUnica(colunas=tuple(colunas_do_indice))
                                )

                    cursor.execute(_TOTAL_LINHAS_SCHEMA_SQL, (schema,))
                    total_linhas_por_tabela: dict[str, int] = {}
                    for nome_tabela, linhas_estimadas in cursor.fetchall():
                        total_linhas_por_tabela[nome_tabela] = max(
                            0, round(linhas_estimadas)
                        )

                    cursor.execute(_LARGURA_MEDIA_LINHA_SCHEMA_SQL, (schema,))
                    largura_media_por_tabela: dict[str, int] = {}
                    for nome_tabela, soma_avg_width in cursor.fetchall():
                        largura_media_por_tabela[nome_tabela] = (
                            int(soma_avg_width)
                            if soma_avg_width
                            else LARGURA_MEDIA_PADRAO_BYTES
                        )

                    cursor.execute(_COLUNAS_COMPRIMIVEIS_SCHEMA_SQL, (schema,))
                    tabelas_com_coluna_comprimivel = frozenset(
                        nome_tabela for (nome_tabela,) in cursor.fetchall()
                    )

                    cursor.execute(_TABELAS_PARTICIONADAS_SCHEMA_SQL, (schema,))
                    tabelas_particionadas = frozenset(
                        nome_tabela for (nome_tabela,) in cursor.fetchall()
                    )

            metadados = _MetadadosDoSchema(
                colunas_por_tabela=dict(colunas_por_tabela),
                pks_por_tabela=dict(pks_por_tabela),
                fks_por_tabela=dict(fks_por_tabela),
                unicas_por_tabela=dict(unicas_por_tabela),
                restricoes_unicas_por_tabela=dict(restricoes_unicas_por_tabela),
                restricoes_fk_compostas_por_tabela=restricoes_fk_compostas_por_tabela,
                total_linhas_por_tabela=total_linhas_por_tabela,
                largura_media_por_tabela=largura_media_por_tabela,
                tabelas_com_coluna_comprimivel=tabelas_com_coluna_comprimivel,
                tabelas_particionadas=tabelas_particionadas,
            )
            self._cache_schemas[schema] = metadados
            return Sucesso(metadados)

    def _largura_media_real(
        self,
        schema: str,
        tabela: str,
        linhas_colunas: list[_LinhaColuna],
        total_linhas: int,
    ) -> Resultado[int]:
        """Mede a largura média real de linha lendo uma amostra física pequena.

        `pg_stats.avg_width` reflete o tamanho armazenado após compressão
        TOAST, não o tamanho que o driver recebe ao ler a linha — para
        colunas comprimíveis, isso pode subestimar bastante a largura real.
        `octet_length(coluna::text)` força a descompressão; `TABLESAMPLE
        SYSTEM` limita o custo da leitura ao tamanho da amostra (mesmo
        mecanismo de `AmostragemPorFaixa`), não ao tamanho da tabela.
        """
        percentual_amostra = min(
            100.0,
            max(0.01, (_LINHAS_AMOSTRA_LARGURA_REAL / total_linhas) * 100),
        )
        with self._conexoes.conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            expressoes_coluna = [
                sql.SQL("COALESCE(octet_length({}::text), 0)").format(
                    sql.Identifier(linha.nome)
                )
                for linha in linhas_colunas
            ]
            soma_colunas = sql.SQL(" + ").join(expressoes_coluna)
            consulta = sql.SQL(
                "SELECT AVG(largura) FROM ("
                "SELECT ({}) AS largura FROM {}.{} "
                "TABLESAMPLE SYSTEM ({}) LIMIT {}"
                ") amostra_largura"
            ).format(
                soma_colunas,
                sql.Identifier(schema),
                sql.Identifier(tabela),
                sql.Literal(percentual_amostra),
                sql.Literal(_LINHAS_AMOSTRA_LARGURA_REAL),
            )
            with conexao.cursor() as cursor:
                cursor.execute(consulta)
                linha_resultado = cursor.fetchone()
                largura_media = linha_resultado[0] if linha_resultado else None
        if largura_media is None:
            return Sucesso(LARGURA_MEDIA_PADRAO_BYTES)
        return Sucesso(max(1, int(largura_media)))

    def _total_blocos(self, schema: str, tabela: str) -> Resultado[int]:
        """Total de blocos de 8KB da tabela, via `pg_relation_size`/`block_size`.

        Só chamada quando a leitura paralela intra-tabela já foi decidida
        como elegível — não faz parte do round-trip de metadados por
        schema, que roda uma vez só e cobre todas as tabelas de uma vez.
        """
        with self._conexoes.conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(_TOTAL_BLOCOS_TABELA_SQL, (schema, tabela))
                linha = cursor.fetchone()
        total_blocos = int(linha[0]) if linha and linha[0] is not None else 0
        return Sucesso(total_blocos)

    def _query_particao_ctid(
        self,
        conexao: conexao_postgres,
        schema: str,
        tabela: str,
        inicio: int,
        fim: int | None,
    ) -> str:
        """Monta o texto SQL de uma faixa de `ctid`, com quoting seguro.

        `connectorx` recebe uma lista de strings SQL prontas (modo de
        particionamento manual), não um cursor — por isso a query é
        renderizada aqui via `sql.Composed.as_string`, em vez de executada
        diretamente como nos outros métodos deste Adapter.
        """
        condicao = sql.SQL("ctid >= {}::tid").format(sql.Literal(f"({inicio},0)"))
        if fim is not None:
            condicao = sql.SQL("{} AND ctid < {}::tid").format(
                condicao, sql.Literal(f"({fim},0)")
            )
        consulta = sql.SQL("SELECT * FROM {}.{} WHERE {}").format(
            sql.Identifier(schema), sql.Identifier(tabela), condicao
        )
        return consulta.as_string(conexao)

    def _ler_tabela_em_paralelo(
        self,
        schema: str,
        tabela: str,
        token: TokenDeReserva,
        total_linhas: int,
        largura_media_bytes: int,
    ) -> Resultado[pl.DataFrame]:
        """Lê a tabela inteira via `connectorx`, uma faixa de `ctid` por conexão.

        `connectorx` decodifica direto do driver pra Arrow/Polars fora do
        GIL (`py.allow_threads` durante a decodificação) — substitui o
        desenho anterior (`ThreadPoolExecutor` + cursor `psycopg2` +
        `pl.DataFrame(orient="row")`), que media só ~15-20% de ganho real
        contra até 4x teórico porque o GIL serializava a decodificação
        (ver `plan/registry-plan/issue-126-paralelismo-intra-tabela.md`).

        A conexão líder exporta um snapshot (`pg_export_snapshot`) e
        mantém a própria transação `REPEATABLE READ` aberta enquanto o
        `connectorx` lê todas as faixas — cada uma numa conexão própria,
        gerenciada pela própria lib (não pelo `ThreadedConnectionPool`
        deste Extrator), que importa o mesmo snapshot via
        `pre_execution_query` (`SET TRANSACTION SNAPSHOT`). Preserva a
        mesma consistência entre faixas que o desenho anterior garantia.

        `token.n` é o total de permits reservados do semáforo (via
        `self._conexoes.reservar`) — a conexão líder consome 1 deles (via
        `self._conexoes.conexao_ja_reservada(token, ...)`, que empresta do
        pool sem tocar o semáforo de novo, assumindo que esse permit já
        está contado aqui). Os `token.n - 1` restantes vão pro `connectorx`,
        senão o uso real de conexões (`token.n` faixas + 1 líder) excederia
        o orçamento que a reserva efetivamente concedeu.
        """
        n_faixas = token.n - 1
        resultado_blocos = self._total_blocos(schema, tabela)
        if isinstance(resultado_blocos, Falha):
            return resultado_blocos
        total_blocos = resultado_blocos.valor
        faixas = particoes_de_blocos(total_blocos, n_faixas)
        _logger.info(
            "'%s.%s': dividindo em %d faixas de blocos (%d blocos no "
            "total, ~%d blocos/faixa) para leitura paralela via "
            "connectorx (+ 1 conexão líder pro snapshot) — todas as "
            "faixas competem pelo mesmo storage físico; se o gargalo "
            "real for I/O sequencial de disco (não CPU de decodificação), "
            "o ganho de paralelizar aqui é limitado, mesmo com múltiplas "
            "conexões.",
            schema,
            tabela,
            n_faixas,
            total_blocos,
            total_blocos // n_faixas if n_faixas else total_blocos,
        )

        with self._conexoes.conexao_ja_reservada(
            token, autocommit=False
        ) as resultado_lider:
            if isinstance(resultado_lider, Falha):
                return resultado_lider
            conexao_lider = resultado_lider.valor
            try:
                with conexao_lider.cursor() as cursor_lider:
                    cursor_lider.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                    )
                    cursor_lider.execute("SELECT pg_export_snapshot()")
                    linha_snapshot = cursor_lider.fetchone()
                    assert linha_snapshot is not None
                    snapshot_id = str(linha_snapshot[0])

                queries = [
                    self._query_particao_ctid(
                        conexao_lider, schema, tabela, inicio, fim
                    )
                    for inicio, fim in faixas
                ]
                try:
                    amostra = cx.read_sql(
                        self._dsn_connectorx,
                        queries,
                        return_type="polars",
                        pre_execution_query=[
                            "BEGIN ISOLATION LEVEL REPEATABLE READ",
                            f"SET TRANSACTION SNAPSHOT '{snapshot_id}'",
                        ],
                    )
                except Exception as erro:  # noqa: BLE001 — crash conhecido do connectorx
                    # (ex.: NUMERIC sem precisão/escala fixa) precisa virar Falha, não
                    # propagar como exceção não tratada pro chamador do Extrator.
                    return Falha(
                        f"Falha ao ler '{schema}.{tabela}' em paralelo via "
                        f"connectorx: {erro}"
                    )
            finally:
                conexao_lider.commit()

        return Sucesso(amostra)

    def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        resultado_estrategia = self._configuracao.estrategia_obrigatoria()
        if isinstance(resultado_estrategia, Falha):
            return resultado_estrategia
        estrategia = resultado_estrategia.valor

        resultado_metadados = self._obter_metadados_schema(schema)
        if isinstance(resultado_metadados, Falha):
            return resultado_metadados
        metadados = resultado_metadados.valor

        linhas_colunas = metadados.colunas_por_tabela.get(tabela)
        if not linhas_colunas:
            return Falha(f"Schema '{schema}' ou tabela '{tabela}' não encontrada.")

        colunas_pk = metadados.pks_por_tabela.get(tabela, set())
        linhas_fk_por_coluna: list[tuple[str, str, str, str]] = []
        for (
            nome_coluna,
            escopo_ref,
            tabela_ref,
            coluna_ref,
            _,
        ) in metadados.fks_por_tabela.get(tabela, []):
            linhas_fk_por_coluna.append(
                (nome_coluna, escopo_ref, tabela_ref, coluna_ref)
            )
        colunas_fk = construir_colunas_fk(linhas_fk_por_coluna)
        avisos: list[Aviso] = []
        colunas_unicas = metadados.unicas_por_tabela.get(tabela, set())
        restricoes_unicas = metadados.restricoes_unicas_por_tabela.get(tabela, [])
        restricoes_fk_compostas = metadados.restricoes_fk_compostas_por_tabela.get(
            tabela, []
        )
        total_linhas = metadados.total_linhas_por_tabela.get(tabela, 0)

        colunas: list[ColunaExtraida] = []
        for linha_coluna in linhas_colunas:
            colunas.append(
                _construir_coluna(linha_coluna, colunas_pk, colunas_fk, colunas_unicas)
            )

        requisicao = estrategia.requisicao
        largura_media_bytes = metadados.largura_media_por_tabela.get(
            tabela, LARGURA_MEDIA_PADRAO_BYTES
        )
        if total_linhas > 0 and tabela in metadados.tabelas_com_coluna_comprimivel:
            resultado_largura = self._largura_media_real(
                schema, tabela, linhas_colunas, total_linhas
            )
            if isinstance(resultado_largura, Falha):
                return resultado_largura
            largura_media_bytes = resultado_largura.valor

        # Paralelismo intra-tabela: só AmostragemIntegral por enquanto (via
        # PercentualDeLinhas/AmostragemPorFaixa com percentual alto ainda
        # não implementada — ver registry-plan da issue #126). Tabela
        # particionada declarativamente nunca é elegível: pg_relation_size
        # sobre a tabela-mãe não mapeia pra nada físico coerente.
        particionada = tabela in metadados.tabelas_particionadas
        elegivel_paralelo = (
            not particionada
            and isinstance(requisicao, AmostragemIntegral)
            and deve_paralelizar_leitura(total_linhas, largura_media_bytes)
        )
        token_reserva: TokenDeReserva | None = None
        if elegivel_paralelo:
            token_reserva = self._conexoes.reservar(self._max_conexoes_por_tabela)
        if token_reserva is not None:
            _logger.info(
                "'%s.%s': paralelismo intra-tabela ativado (~%d linhas, "
                "%d conexões).",
                schema,
                tabela,
                total_linhas,
                token_reserva.n,
            )
            try:
                resultado_leitura = self._ler_tabela_em_paralelo(
                    schema, tabela, token_reserva, total_linhas, largura_media_bytes
                )
            finally:
                self._conexoes.liberar(token_reserva)
            if isinstance(resultado_leitura, Falha):
                # connectorx pode crashar em casos conhecidos (ex.: NUMERIC
                # sem precisão/escala fixa) — cair pro caminho sequencial
                # abaixo em vez de derrubar a tabela inteira, que lia essa
                # mesma tabela sem problema antes do paralelismo existir.
                _logger.warning(
                    "'%s.%s': leitura paralela via connectorx falhou, "
                    "caindo para o caminho sequencial. Detalhe técnico: %s",
                    schema,
                    tabela,
                    resultado_leitura.erro,
                )
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"'{schema}.{tabela}': leitura paralela via "
                            "connectorx falhou — extraída pelo caminho "
                            "sequencial em vez disso. Ver o log para o "
                            "detalhe técnico da falha."
                        ),
                        origem="ExtratorPostgres",
                    )
                )
            else:
                amostra_paralela = resultado_leitura.valor
                metadados_amostra, avisos_amostra = construir_metadados_de_amostra(
                    nome=estrategia.nome,
                    requisicao=requisicao,
                    tamanho_amostra=len(amostra_paralela),
                    total_linhas=len(amostra_paralela),
                    origem="ExtratorPostgres",
                    causa_provavel="sem ANALYZE recente",
                    identificador_tabela=f"{schema}.{tabela}",
                )
                avisos.extend(avisos_amostra)
                return Sucesso(
                    TabelaExtraida(
                        nome_tabela=tabela,
                        nome_escopo=schema,
                        colunas=colunas,
                        total_linhas=len(amostra_paralela),
                        amostra=amostra_paralela,
                        metadados_amostra=metadados_amostra,
                        restricoes_unicas=restricoes_unicas,
                        restricoes_fk_compostas=restricoes_fk_compostas,
                    ),
                    avisos=avisos,
                )

        usa_streaming = deve_usar_streaming(total_linhas, largura_media_bytes)
        if usa_streaming:
            _logger.info(
                "'%s.%s': streaming ativado (~%d linhas, ~%d bytes/linha) — "
                "cursor nomeado mantém transação aberta pela duração da leitura.",
                schema,
                tabela,
                total_linhas,
                largura_media_bytes,
            )
        with self._conexoes.conexao(autocommit=not usa_streaming) as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
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
                case RequisicaoPorFaixa(percentual=percentual, seed=seed):
                    seed_usado = seed_efetivo(seed)
                    requisicao_efetiva = RequisicaoPorFaixa(
                        percentual=percentual, seed=seed_usado
                    )
                    consulta_amostra = sql.SQL(
                        "SELECT * FROM {}.{} TABLESAMPLE SYSTEM ({}) "
                        "REPEATABLE ({})"
                    ).format(
                        sql.Identifier(schema),
                        sql.Identifier(tabela),
                        sql.Literal(percentual),
                        sql.Literal(seed_usado),
                    )
                case _ as nunca:
                    assert_never(nunca)

            if usa_streaming:
                tamanho_lote = calcular_tamanho_lote(largura_media_bytes)
                with conexao.cursor(name=f"amostra_{schema}_{tabela}") as cursor:
                    cursor.itersize = tamanho_lote
                    cursor.execute(consulta_amostra)
                    amostra = ler_amostra_em_lotes(cursor, tamanho_lote)
                conexao.commit()
            else:
                with conexao.cursor() as cursor:
                    cursor.execute(consulta_amostra)
                    amostra = ler_amostra_fetchall(cursor)

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
                origem="ExtratorPostgres",
                causa_provavel="sem ANALYZE recente",
                identificador_tabela=f"{schema}.{tabela}",
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
                    restricoes_unicas=restricoes_unicas,
                    restricoes_fk_compostas=restricoes_fk_compostas,
                ),
                avisos=avisos,
            )

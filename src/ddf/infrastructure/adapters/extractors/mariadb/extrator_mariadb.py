"""Extrator concreto para bancos MariaDB."""

import logging
import random
import threading
from typing import assert_never
from urllib.parse import quote

import connectorx as cx
import polars as pl
import pymysql

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
    RequisicaoPorFaixa,
)
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.extractors.comum.construir_colunas_fk import (
    construir_colunas_fk,
)
from ddf.infrastructure.adapters.extractors.comum.construir_metadados_de_amostra import (  # noqa: E501
    construir_metadados_de_amostra,
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
from ddf.infrastructure.adapters.extractors.mariadb._conexoes import (
    TokenDeReserva,
    _GerenciadorDeConexoesMariaDB,
)
from ddf.infrastructure.adapters.extractors.mariadb._construcao import (
    _construir_coluna,
    _elegibilidade_de_pk_para_faixa,
    _MetadadosDoSchema,
    _PkElegivel,
    _PkNaoElegivel,
    _promover_booleanos_pela_amostra,
    _quotar_identificador,
    montar_metadados_do_schema,
    particionar_faixas_exaustivas,
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

_K_FAIXAS_MINIMO = 10
_K_FAIXAS_MAXIMO = 50
_LINHAS_POR_FAIXA_ADICIONAL = 100_000


def _k_faixas_para(total_linhas: int) -> int:
    """Nº de faixas contíguas sorteadas independentemente em RequisicaoPorFaixa.

    Aproxima o comportamento de blocos espalhados do TABLESAMPLE SYSTEM do
    Postgres sem exigir uma consulta por linha amostrada (inviável em lote).
    Fixo em `_K_FAIXAS_MINIMO` até 1M linhas, cresce depois disso: K
    constante em tabelas muito grandes concentra a amostra em poucos blocos
    de PK, sujeito a viés de correlação PK↔atributo (ex.: autoincrement
    correlacionado a data de inserção) mesmo com faixas espalhadas.
    """
    return min(
        _K_FAIXAS_MAXIMO,
        max(_K_FAIXAS_MINIMO, total_linhas // _LINHAS_POR_FAIXA_ADICIONAL),
    )


_logger = logging.getLogger(__name__)


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
        max_conexoes_por_tabela: int | None = None,
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
            max_conexoes_por_tabela: teto de conexões que uma única tabela
                grande tenta reservar pra ler em paralelo internamente via
                `connectorx` — mesmo parâmetro/default (`min(4,
                max_conexoes)`) do `ExtratorPostgres`.

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
        self._host = host
        self._user = user
        self._password = password
        self._configuracao = configuracao
        self._port = port
        self._max_conexoes_por_tabela = max_conexoes_por_tabela
        self._conexoes = _GerenciadorDeConexoesMariaDB(
            host, user, password, port, max_conexoes, connect_timeout
        )
        self._cache_schemas: dict[str, _MetadadosDoSchema] = {}
        self._lock_cache_schemas = threading.Lock()
        self._aviso_paralelismo_emitido = False
        self._lock_aviso_paralelismo = threading.Lock()

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos (databases) disponíveis, ordenados por nome."""
        with self._conexoes.conexao() as resultado_conexao:
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
        with self._conexoes.conexao() as resultado_conexao:
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

            with self._conexoes.conexao() as resultado_conexao:
                if isinstance(resultado_conexao, Falha):
                    return resultado_conexao
                conexao = resultado_conexao.valor
                with conexao.cursor() as cursor:
                    cursor.execute(_COLUNAS_SQL, (escopo,))
                    linhas_colunas = cursor.fetchall()
                    cursor.execute(_CHAVES_PRIMARIAS_SQL, (escopo,))
                    linhas_pks = cursor.fetchall()
                    cursor.execute(_CHAVES_ESTRANGEIRAS_SQL, (escopo,))
                    linhas_fks = cursor.fetchall()
                    cursor.execute(_COLUNAS_UNICAS_SQL, (escopo,))
                    linhas_unicas = cursor.fetchall()
                    cursor.execute(_COLUNAS_JSON_SQL, (escopo,))
                    linhas_json = cursor.fetchall()
                    cursor.execute(_TOTAL_LINHAS_SQL, (escopo,))
                    linhas_total_linhas = cursor.fetchall()

            metadados = montar_metadados_do_schema(
                linhas_colunas,
                linhas_pks,
                linhas_fks,
                linhas_unicas,
                linhas_json,
                linhas_total_linhas,
            )
            self._cache_schemas[escopo] = metadados
            return Sucesso(metadados)

    def _emitir_aviso_paralelismo_se_necessario(self, avisos: list[Aviso]) -> None:
        """Emite o Aviso de risco de consistência uma única vez por execução.

        MariaDB não tem equivalente ao `pg_export_snapshot`/`SET
        TRANSACTION SNAPSHOT` do Postgres (`FLUSH TABLES WITH READ LOCK`
        trava o servidor inteiro, rejeitado) — cada faixa paralela lê sob
        sua própria transação, sem garantia de consistência entre elas.
        Flag de instância protegida por lock evita repetir o mesmo texto
        uma vez por tabela elegível (mesmo ruído que a #116 já corrigiu
        pro viés de cluster de `AmostragemPorFaixa`) — não dá pra mover
        pro wizard porque a ativação depende do tamanho real da tabela, só
        conhecido em runtime.
        """
        with self._lock_aviso_paralelismo:
            if self._aviso_paralelismo_emitido:
                return
            self._aviso_paralelismo_emitido = True
        avisos.append(
            Aviso(
                mensagem=(
                    "Paralelismo intra-tabela ativado neste MariaDB sem "
                    "garantia de consistência entre faixas — o motor não "
                    "tem equivalente ao SET TRANSACTION SNAPSHOT do "
                    "Postgres. Escritas concorrentes durante a extração "
                    "podem produzir uma amostra combinada de estados "
                    "diferentes da tabela."
                ),
                origem="ExtratorMariaDB",
            )
        )

    def _dominio_de_pk(
        self, escopo: str, tabela: str, nome_pk: str
    ) -> Resultado[tuple[int, int]]:
        """Sonda `MIN`/`MAX` do PK via conexão normal, fora de qualquer reserva.

        Chamado por `extrair_tabela` **antes** de `reservar_conexoes` —
        nesse ponto o semáforo ainda não tem nenhum permit desta tabela
        retido, então o `acquire`/`release` normal de `_conexao()` não
        compete com nada que a própria call-stack já segure. Chamar isso
        de dentro de `_ler_tabela_em_paralelo` (depois da reserva) causava
        um self-deadlock real quando `n_reservado` esgotava o semáforo:
        `_conexao()` ficava bloqueada esperando um permit que só a própria
        thread, já travada, poderia devolver.
        """
        identificador_tabela = (
            f"{_quotar_identificador(escopo)}.{_quotar_identificador(tabela)}"
        )
        identificador_pk = _quotar_identificador(nome_pk)
        with self._conexoes.conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            with conexao.cursor() as cursor:
                cursor.execute(
                    f"SELECT MIN({identificador_pk}), MAX({identificador_pk}) "
                    f"FROM {identificador_tabela}"
                )
                linha_dominio = cursor.fetchone()
        minimo, maximo = linha_dominio if linha_dominio else (None, None)
        if minimo is None or maximo is None:
            return Falha(
                f"'{escopo}.{tabela}': tabela vazia, não elegível a "
                "paralelismo intra-tabela."
            )
        return Sucesso((minimo, maximo))

    def _ler_tabela_em_paralelo(
        self,
        escopo: str,
        tabela: str,
        nome_pk: str,
        minimo: int,
        maximo: int,
        token: TokenDeReserva,
    ) -> Resultado[pl.DataFrame]:
        """Lê a tabela inteira via `connectorx`, uma faixa contígua de PK por conexão.

        Sem conexão líder nem snapshot: diferente do `ExtratorPostgres`,
        não há mecanismo de consistência entre faixas a coordenar aqui —
        cada faixa de `connectorx` é só uma query independente contra o
        mesmo `nome_pk` (risco aceito, ver
        `_emitir_aviso_paralelismo_se_necessario`). `minimo`/`maximo`
        (domínio do PK) já vêm calculados por `_dominio_de_pk`, chamado
        antes da reserva de conexões — ver docstring de lá.
        `particionar_faixas_exaustivas` gera as faixas (mesmo algoritmo de
        `ctid` do Postgres, aplicado a valor de PK em vez de bloco físico) —
        `token.n` é quantas conexões `self._conexoes.reservar` concedeu,
        mesmo que nenhuma delas seja emprestada aqui (ver docstring do
        módulo `_conexoes.py`: o MariaDB não tem `conexao_ja_reservada`
        porque o `connectorx` sempre abre conexão própria via DSN).
        """
        identificador_tabela = (
            f"{_quotar_identificador(escopo)}.{_quotar_identificador(tabela)}"
        )
        identificador_pk = _quotar_identificador(nome_pk)
        faixas = particionar_faixas_exaustivas(minimo, maximo, token.n)
        _logger.info(
            "'%s.%s': dividindo em %d faixas de PK '%s' (%d..%d) para "
            "leitura paralela via connectorx.",
            escopo,
            tabela,
            token.n,
            nome_pk,
            minimo,
            maximo,
        )
        queries: list[str] = []
        for inicio, fim in faixas:
            condicao = f"{identificador_pk} >= {inicio}"
            if fim is not None:
                condicao += f" AND {identificador_pk} < {fim}"
            queries.append(f"SELECT * FROM {identificador_tabela} WHERE {condicao}")

        # Sem connect_timeout na DSN aqui, ao contrário do ExtratorPostgres:
        # testado empiricamente (`connect_timeout`, `connect-timeout`,
        # `timeout`, `connectTimeout`) — o driver MySQL do connectorx
        # rejeita todos com "Unknown URL parameter", diferente do driver
        # Postgres (baseado em libpq/tokio-postgres, aceita `connect_timeout`
        # de verdade). Host inacessível nas conexões que o connectorx abre
        # aqui continua sem essa proteção — risco aceito, sem alternativa
        # de baixo custo encontrada.
        dsn = (
            f"mysql://{quote(self._user, safe='')}:"
            f"{quote(self._password, safe='')}@{self._host}:{self._port}/"
            f"{quote(escopo, safe='')}"
        )
        try:
            amostra = cx.read_sql(dsn, queries, return_type="polars")
        except Exception as erro:  # noqa: BLE001 — crash conhecido do connectorx
            return Falha(
                f"Falha ao ler '{escopo}.{tabela}' em paralelo via connectorx: {erro}"
            )
        return Sucesso(amostra)

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

        largura_media_bytes = metadados.largura_media_por_tabela.get(
            tabela, LARGURA_MEDIA_PADRAO_BYTES
        )

        # Paralelismo intra-tabela: só AmostragemIntegral por enquanto,
        # mesmo escopo fatiado do ExtratorPostgres (item 4a/4b da #126) —
        # e só quando a PK é elegível para virar faixa contígua
        # (_elegibilidade_de_pk_para_faixa, mesma checagem que
        # RequisicaoPorFaixa já usa). Sem detecção de tabela particionada
        # nativa do MariaDB — fora do escopo desta rodada.
        requisicao = estrategia.requisicao
        pk_elegivel: _PkElegivel | None = None
        elegivel_paralelo = isinstance(
            requisicao, AmostragemIntegral
        ) and deve_paralelizar_leitura(total_linhas, largura_media_bytes)
        if elegivel_paralelo:
            elegibilidade_pk = _elegibilidade_de_pk_para_faixa(
                colunas_pk, linhas_colunas
            )
            if isinstance(elegibilidade_pk, _PkElegivel):
                pk_elegivel = elegibilidade_pk
            else:
                elegivel_paralelo = False

        # Sonda MIN/MAX antes de reservar_conexoes, de propósito: fora da
        # janela em que o semáforo tem permits desta tabela retidos, pra
        # não arriscar self-deadlock (ver docstring de _dominio_de_pk).
        dominio_pk: tuple[int, int] | None = None
        if elegivel_paralelo:
            assert pk_elegivel is not None
            resultado_dominio = self._dominio_de_pk(
                escopo, tabela, pk_elegivel.nome_coluna
            )
            if isinstance(resultado_dominio, Sucesso):
                dominio_pk = resultado_dominio.valor
            else:
                elegivel_paralelo = False

        token_reserva: TokenDeReserva | None = None
        if elegivel_paralelo:
            token_reserva = self._conexoes.reservar(self._max_conexoes_por_tabela)
        if token_reserva is not None:
            assert pk_elegivel is not None
            assert dominio_pk is not None
            _logger.info(
                "'%s.%s': paralelismo intra-tabela ativado (~%d linhas, "
                "%d conexões).",
                escopo,
                tabela,
                total_linhas,
                token_reserva.n,
            )
            minimo, maximo = dominio_pk
            try:
                resultado_leitura = self._ler_tabela_em_paralelo(
                    escopo,
                    tabela,
                    pk_elegivel.nome_coluna,
                    minimo,
                    maximo,
                    token_reserva,
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
                    escopo,
                    tabela,
                    resultado_leitura.erro,
                )
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"'{escopo}.{tabela}': leitura paralela via "
                            "connectorx falhou — extraída pelo caminho "
                            "sequencial em vez disso. Ver o log para o "
                            "detalhe técnico da falha."
                        ),
                        origem="ExtratorMariaDB",
                    )
                )
            else:
                self._emitir_aviso_paralelismo_se_necessario(avisos)
                amostra_paralela = resultado_leitura.valor
                colunas = _promover_booleanos_pela_amostra(
                    colunas, amostra_paralela, candidatos_booleanos
                )
                metadados_amostra, avisos_amostra = construir_metadados_de_amostra(
                    nome="tabela_inteira",
                    requisicao=requisicao,
                    tamanho_amostra=len(amostra_paralela),
                    total_linhas=len(amostra_paralela),
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
            avisos.append(
                Aviso(
                    mensagem=(
                        f"'{escopo}.{tabela}': streaming ativado (~{total_linhas} "
                        f"linhas, ~{largura_media_bytes} bytes/linha) — SSCursor "
                        "lê em lotes em vez de fetchall()."
                    ),
                    origem="ExtratorMariaDB",
                )
            )
        with self._conexoes.conexao() as resultado_conexao:
            if isinstance(resultado_conexao, Falha):
                return resultado_conexao
            conexao = resultado_conexao.valor
            cursor_bruto = (
                conexao.cursor(pymysql.cursors.SSCursor)
                if usa_streaming
                else conexao.cursor()
            )
            # `with` garante `cursor.close()` determinístico antes de
            # qualquer exceção propagar — SSCursor não drenado, deixado
            # para o GC fechar via `__del__`, gera AttributeError
            # silenciosamente engolido (achado do engenheiro de dados),
            # mascarando a causa raiz real do erro.
            with cursor_bruto as cursor:
                requisicao_efetiva: RequisicaoDeAmostragem
                identificador_tabela = (
                    f"{_quotar_identificador(escopo)}.{_quotar_identificador(tabela)}"
                )
                n_pedido_por_faixa: int | None = None
                k_faixas = _k_faixas_para(total_linhas)
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
                                    1, n_pedido_por_faixa // k_faixas
                                )
                                # Corte sorteado em Python, não via RAND()
                                # no SQL: dentro de um WHERE, RAND(seed) do
                                # MariaDB é reavaliado a cada linha varrida
                                # pelo motor, não uma vez só — usá-lo ali
                                # faria o corte derivar para o início do
                                # intervalo de PK, independente do seed.
                                rng_faixas = random.Random(seed_usado)
                                subconsultas: list[str] = []
                                parametros: list[object] = []
                                for _ in range(k_faixas):
                                    cutoff = (
                                        rng_faixas.randint(0, max_pk)
                                        if max_pk is not None
                                        else 0
                                    )
                                    subconsultas.append(
                                        f"(SELECT * FROM {identificador_tabela} "
                                        f"WHERE {identificador_pk} >= %s "
                                        f"ORDER BY {identificador_pk} LIMIT %s)"
                                    )
                                    parametros.extend([cutoff, linhas_por_faixa])
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

                if usa_streaming:
                    tamanho_lote = calcular_tamanho_lote(largura_media_bytes)
                    amostra = ler_amostra_em_lotes(cursor, tamanho_lote)
                else:
                    amostra = ler_amostra_fetchall(cursor)

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
                    nome_efetivo = "tabela_inteira"
                case AmostragemProbabilistica():
                    total_linhas_final = total_linhas
                    nome_efetivo = "percentual_de_linhas"
                case RequisicaoPorFaixa():
                    total_linhas_final = total_linhas
                    nome_efetivo = "amostragem_por_faixa"
                case _ as nunca:
                    assert_never(nunca)

            metadados_amostra, avisos_amostra = construir_metadados_de_amostra(
                # nome_efetivo, não estrategia.nome: no fallback de PK não
                # elegível, requisicao_efetiva vira AmostragemProbabilistica
                # mesmo com estrategia="amostragem_por_faixa" escolhida no
                # wizard — o mecanismo real de leitura é o que importa aqui,
                # não a escolha original do usuário.
                nome=nome_efetivo,
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

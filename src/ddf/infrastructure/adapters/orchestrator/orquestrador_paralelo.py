"""Orquestração paralela de extração e aplicação de sobrescritas."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.estagio import Estagio
from ddf.pipeline.seguranca import executar_com_seguranca

_Item = TypeVar("_Item")
_Saida = TypeVar("_Saida")

_ORIGEM = "OrquestradorParalelo"


def _avisos_de_falhas(verbo: str, falhas: list[tuple[str, str]]) -> list[Aviso]:
    """Converte falhas individuais em Aviso, uma mensagem por item que falhou.

    Args:
        verbo: ação que falhou (ex.: "extrair", "aplicar sobrescrita em").
        falhas: pares (identificador, mensagem de erro) de cada falha.

    Returns:
        Um Aviso por falha, com origem "OrquestradorParalelo".
    """
    return [
        Aviso(mensagem=f"Falha ao {verbo} '{identificador}': {erro}", origem=_ORIGEM)
        for identificador, erro in falhas
    ]


def _grupos_de_chave_candidata(tabela: TabelaExtraida) -> list[frozenset[str]]:
    """Todos os grupos de colunas que garantem unicidade nesta tabela.

    Reúne PK (single ou composta, pelas colunas marcadas `chave_primaria`),
    UNIQUE single-column (`coluna.unica`) e UNIQUE composto
    (`restricoes_unicas`) — qualquer um desses grupos é candidato válido
    pro lado referenciado de uma FK composta.
    """
    grupos: list[frozenset[str]] = []
    colunas_pk = {coluna.nome for coluna in tabela.colunas if coluna.chave_primaria}
    if colunas_pk:
        grupos.append(frozenset(colunas_pk))
    for coluna in tabela.colunas:
        if coluna.unica:
            grupos.append(frozenset({coluna.nome}))
    for restricao in tabela.restricoes_unicas:
        grupos.append(frozenset(restricao.colunas))
    return grupos


def _avisos_de_fk_composta_sem_chave_candidata(
    tabelas: list[TabelaExtraida],
) -> list[Aviso]:
    """Emite Aviso quando uma FK composta não aponta para PK/UNIQUE conhecida.

    Checagem cross-table (precisa de todas as tabelas do escopo já
    extraídas), por isso roda aqui — depois que `extrair` já paralelizou a
    extração de todas as tabelas — em vez de dentro de cada `Extrator`
    concreto, que só enxerga uma tabela por vez. Banco legado malformado
    (FK apontando para colunas que a própria fonte não garante como únicas
    do lado referenciado) é raro, mas real — sem este Aviso, a
    `RestricaoDeFkComposta` seria consumida silenciosamente como se a
    integridade referencial estivesse garantida.

    Tabela referenciada fora do lote analisado nesta execução também gera
    um Aviso, mas de teor distinto (não verificável, não "verificado e
    correto") — um `continue` silencioso aqui seria indistinguível de
    "checado e ok".

    Args:
        tabelas: tabelas já extraídas neste lote, mesma lista que `extrair`
            devolve.

    Returns:
        Um Aviso por `RestricaoDeFkComposta` cujo lado referenciado está
        fora do lote (não verificável) ou está no lote mas não corresponde
        a nenhum grupo de chave candidata (verificado e malformado).
    """
    tabelas_por_chave = {(t.nome_escopo, t.nome_tabela): t for t in tabelas}
    avisos: list[Aviso] = []
    for tabela in tabelas:
        for restricao in tabela.restricoes_fk_compostas:
            chave_referenciada = (
                restricao.nome_escopo_referenciado,
                restricao.nome_tabela_referenciada,
            )
            origem_tabela = f"{tabela.nome_escopo}.{tabela.nome_tabela}"
            colunas_locais = ", ".join(restricao.colunas_locais)
            destino_tabela = f"{chave_referenciada[0]}.{chave_referenciada[1]}"

            tabela_referenciada = tabelas_por_chave.get(chave_referenciada)
            if tabela_referenciada is None:
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"FK composta de '{origem_tabela}' ({colunas_locais}) "
                            f"aponta para '{destino_tabela}', fora do lote "
                            "analisado nesta execução — integridade "
                            "referencial não verificada."
                        ),
                        origem=_ORIGEM,
                    )
                )
                continue

            grupos_chave = _grupos_de_chave_candidata(tabela_referenciada)
            colunas_referenciadas = frozenset(restricao.colunas_referenciadas)
            if colunas_referenciadas not in grupos_chave:
                colunas_ref = ", ".join(restricao.colunas_referenciadas)
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"FK composta de '{origem_tabela}' ({colunas_locais}) "
                            f"aponta para '{destino_tabela}' ({colunas_ref}), que "
                            "não corresponde a nenhuma chave primária/UNIQUE "
                            "conhecida do lado referenciado — integridade "
                            "referencial pode não estar garantida pelo schema."
                        ),
                        origem=_ORIGEM,
                    )
                )
    return avisos


class OrquestradorParalelo:
    """Coordena extração e aplicação de sobrescritas em paralelo via threads."""

    def __init__(self, max_trabalhadores: int = 8) -> None:
        """Guarda o teto de threads usadas para paralelizar as duas fases.

        Args:
            max_trabalhadores: nº máximo de chamadas concorrentes por fase —
                higiene de recurso local, sem relação com concorrência segura
                contra a fonte (cada Extrator concreto já garante isso
                internamente).

        Raises:
            ValueError: se `max_trabalhadores` não for positivo.
        """
        if max_trabalhadores <= 0:
            raise ValueError(
                f"max_trabalhadores deve ser positivo ({max_trabalhadores})."
            )
        self._max_trabalhadores = max_trabalhadores

    def _executar_em_paralelo(
        self,
        nome_estagio: str,
        itens: list[_Item],
        funcao: Callable[[_Item], Resultado[_Saida]],
        identificador: Callable[[_Item], str],
        progresso: Callable[[str], None] | None = None,
        inicio: Callable[[str], None] | None = None,
    ) -> tuple[list[_Saida], list[Aviso], list[tuple[str, str]]]:
        """Executa `funcao` em paralelo sobre `itens`, acumulando sucessos e falhas.

        Cada chamada roda dentro de `executar_com_seguranca` — uma exceção
        não prevista levantada por `funcao` (ex.: dentro de um `Extrator`
        concreto) viraria uma exceção crua propagada por `futuro.result()`
        sem essa proteção, quebrando os demais itens do lote em vez de
        virar uma falha isolada, acumulada como as demais.

        `progresso`, se informado, é chamado uma vez por item concluído
        (sucesso ou falha) — sempre a partir do laço `as_completed` que roda
        na thread principal, nunca dentro de um worker, por isso dispensa
        lock: as chamadas já são seriais por construção.

        `inicio`, se informado, é chamado uma vez por item, de dentro do
        próprio worker, assim que ele começa a processar — antes de
        `progresso`, nunca depois. Ao contrário de `progresso`, `inicio`
        pode disparar concorrentemente para itens diferentes (um worker por
        thread); thread-safety é responsabilidade de quem implementa o
        callback, não deste método.

        Args:
            nome_estagio: identificador do Estagio chamado por `funcao`
                (ex.: "Extrator", "Sobrescrita"), usado como prefixo na
                mensagem de falha inesperada.
            itens: itens de entrada, um por chamada de `funcao`.
            funcao: transformação aplicada a cada item, retornando um Resultado.
            identificador: extrai o identificador textual de um item, usado
                para nomear o item numa falha ou numa chamada de progresso.
            progresso: callback opcional invocado com o identificador de cada
                item assim que ele termina de processar.
            inicio: callback opcional invocado com o identificador de cada
                item assim que um worker começa a processá-lo.

        Returns:
            Tupla (sucessos, avisos, falhas) — avisos de todo Resultado
            individual (sucesso ou falha) preservados; falhas como
            (identificador, erro).
        """
        sucessos: list[_Saida] = []
        avisos: list[Aviso] = []
        falhas: list[tuple[str, str]] = []

        def _funcao_segura(item: _Item) -> Resultado[_Saida]:
            if inicio is not None:
                inicio(identificador(item))
            return executar_com_seguranca(
                f"{nome_estagio}[{identificador(item)}]", lambda: funcao(item)
            )

        with ThreadPoolExecutor(max_workers=self._max_trabalhadores) as executor:
            futuros = {executor.submit(_funcao_segura, item): item for item in itens}
            for futuro in as_completed(futuros):
                item = futuros[futuro]
                resultado = futuro.result()
                avisos.extend(resultado.avisos)
                if isinstance(resultado, Falha):
                    falhas.append((identificador(item), resultado.erro))
                else:
                    sucessos.append(resultado.valor)
                if progresso is not None:
                    progresso(identificador(item))

        return sucessos, avisos, falhas

    def extrair(
        self,
        escopos: list[str],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
        ao_conhecer_total: Callable[[int], None] | None = None,
        inicio: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Lista e extrai, em paralelo, todas as tabelas dos escopos informados.

        Falha ao listar um escopo ou extrair uma tabela nunca aborta o lote
        inteiro — vira Aviso, e as demais tabelas seguem sendo processadas.

        Args:
            escopos: escopos cujas tabelas serão listadas e extraídas.
            extrator: Extrator concreto usado para listar/extrair cada tabela.
            progresso: callback opcional invocado com "<escopo>.<tabela>" a
                cada tabela concluída (sucesso ou falha).
            ao_conhecer_total: callback opcional invocado uma vez, logo após
                a listagem interna terminar, com o nº de pares (escopo,
                tabela) que de fato serão extraídos.
            inicio: callback opcional invocado com "<escopo>.<tabela>" assim
                que um worker começa a extrair a tabela, de dentro do
                próprio worker (pode disparar concorrentemente).

        Returns:
            Sucesso com list[TabelaExtraida] ordenada por (nome_escopo,
            nome_tabela) — pode ser menor que o total pedido — e um Aviso
            por escopo/tabela que falhou, mais um Aviso por
            RestricaoDeFkComposta cujo lado referenciado (se presente no
            lote) não corresponde a nenhuma PK/UNIQUE conhecida — checagem
            cross-table, só possível aqui, depois que todas as tabelas do
            lote já foram extraídas.
        """
        pares_a_extrair: list[tuple[str, str]] = []
        avisos_listagem: list[Aviso] = []

        for escopo in escopos:
            resultado_listagem = extrator.listar_tabelas(escopo)
            if isinstance(resultado_listagem, Falha):
                avisos_listagem.append(
                    Aviso(
                        mensagem=(
                            f"Falha ao listar tabelas de '{escopo}': "
                            f"{resultado_listagem.erro}"
                        ),
                        origem=_ORIGEM,
                    )
                )
                continue
            pares_a_extrair.extend(resultado_listagem.valor)

        if ao_conhecer_total is not None:
            ao_conhecer_total(len(pares_a_extrair))

        tabelas, avisos_extracao, falhas_extracao = self._executar_em_paralelo(
            "Extrator",
            pares_a_extrair,
            lambda par: extrator.extrair_tabela(*par),
            lambda par: f"{par[0]}.{par[1]}",
            progresso,
            inicio,
        )

        tabelas.sort(key=lambda tabela: (tabela.nome_escopo, tabela.nome_tabela))
        avisos = (
            avisos_listagem
            + avisos_extracao
            + _avisos_de_falhas("extrair", falhas_extracao)
            + _avisos_de_fk_composta_sem_chave_candidata(tabelas)
        )
        return Sucesso(tabelas, avisos=avisos)

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        progresso: Callable[[str], None] | None = None,
        inicio: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Aplica, em paralelo, a Sobrescrita sobre cada TabelaExtraida.

        Falha ao aplicar a sobrescrita de uma tabela nunca aborta o lote
        inteiro — vira Aviso, e as demais tabelas seguem sendo processadas.

        Args:
            tabelas: tabelas extraídas a curar.
            sobrescrita: Estagio que traduz TabelaExtraida em TabelaCurada.
            progresso: callback opcional invocado com "<escopo>.<tabela>" a
                cada tabela concluída (sucesso ou falha).
            inicio: callback opcional invocado com "<escopo>.<tabela>" assim
                que um worker começa a aplicar a sobrescrita, de dentro do
                próprio worker (pode disparar concorrentemente).

        Returns:
            Sucesso com BancoCurado (tabelas ordenadas por (nome_escopo,
            nome_tabela) — pode ser menor que o total pedido) e um Aviso por
            tabela cuja sobrescrita falhou, além dos Avisos que a própria
            Sobrescrita emitiu (ex.: skeleton criado/atualizado).
        """
        tabelas_curadas, avisos_sobrescrita, falhas = self._executar_em_paralelo(
            "Sobrescrita",
            tabelas,
            sobrescrita,
            lambda tabela: f"{tabela.nome_escopo}.{tabela.nome_tabela}",
            progresso,
            inicio,
        )

        tabelas_curadas.sort(
            key=lambda tabela: (tabela.nome_escopo, tabela.nome_tabela)
        )
        avisos = avisos_sobrescrita + _avisos_de_falhas(
            "aplicar sobrescrita em", falhas
        )
        return Sucesso(BancoCurado(tabelas=tabelas_curadas), avisos=avisos)

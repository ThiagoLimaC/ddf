"""Helpers de interação do wizard — único módulo que importa `questionary`."""

import itertools
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import NamedTuple, TypeVar, cast

import questionary

_Numero = TypeVar("_Numero", int, float)

_QUADROS_AMPULHETA = ("⏳", "⌛")

COR_DESTAQUE = "#00d7ff"
COR_SUCESSO = "#00d700"

# Cinza fosco/dimmed para texto de contexto (ex.: mensagem de boas-vindas),
# em segundo plano deliberado perante COR_DESTAQUE/COR_SUCESSO. Mesmo tom
# usado por `gh` para texto secundário (`Gray()`, ANSI 256 cor 242 ≈ RGB
# 108,108,108) — legível sobre fundo escuro ou claro, sem competir com as
# cores vivas reservadas a decisões e resultados.
COR_SECUNDARIA = "#6c6c6c"

# Largura fixa (não segue o terminal) para o rótulo ficar sempre centralizado
# de forma previsível — inclusive em teste, sem depender de mock de
# get_terminal_size.
_LARGURA_CABECALHO_ETAPA = 70

# Mesmo tom do banner (_BANNER em wizard.py) — resposta do usuário destacada
# na mesma cor. É um teste de identidade visual; ajustar/reverter é só mudar
# esta constante.
_ESTILO = questionary.Style([("answer", f"fg:{COR_DESTAQUE} bold")])


def texto(mensagem: str, default: str = "", dica_limpar: bool = False) -> str:
    """Pergunta um texto livre, saindo limpo se o usuário cancelar (Ctrl+C/Esc).

    questionary captura o KeyboardInterrupt internamente e devolve None em
    vez de propagar — sem essa checagem, cada prompt cancelado quebraria em
    um TypeError diferente lá na frente (ex.: Path(None)), em vez de sair.

    Args:
        mensagem: pergunta exibida ao usuário.
        default: valor pré-preenchido no campo.
        dica_limpar: exibe a dica "(Ctrl+U limpa o valor pré-preenchido)" —
            só vale a pena quando o default é longo o suficiente pra ser
            incômodo apagar manualmente (ex.: connection string).
    """
    print()
    instrucao = (
        "(Ctrl+U limpa o valor pré-preenchido)" if dica_limpar and default else None
    )
    resposta = cast(
        "str | None",
        questionary.text(
            mensagem, default=default, instruction=instrucao, style=_ESTILO
        ).ask(),
    )
    if resposta is None:
        sys.exit(0)
    return resposta


def numero(
    mensagem: str, conversor: Callable[[str], _Numero], default: str = ""
) -> _Numero:
    """Pergunta um número, repetindo até que `conversor` consiga interpretar.

    Sem isso, `int()`/`float()` aplicado direto na resposta livre de
    `texto()` derruba o wizard com um ValueError cru assim que o usuário
    digita algo não numérico — mesmo espírito de `ou_sair` (avisos.py):
    nunca deixar um erro técnico chegar bruto no terminal.

    Args:
        mensagem: pergunta exibida ao usuário.
        conversor: `int` ou `float`.
        default: valor pré-preenchido no campo.
    """
    while True:
        resposta = texto(mensagem, default=default)
        try:
            return conversor(resposta)
        except ValueError:
            print(f"Erro: valor inválido ({resposta!r}). Tente novamente.")


def numero_opcional(
    mensagem: str, conversor: Callable[[str], _Numero], default: str = ""
) -> _Numero | None:
    """Como `numero()`, mas resposta em branco devolve None em vez de repetir.

    Args:
        mensagem: pergunta exibida ao usuário.
        conversor: `int` ou `float`.
        default: valor pré-preenchido no campo.
    """
    while True:
        resposta = texto(mensagem, default=default)
        if not resposta:
            return None
        try:
            return conversor(resposta)
        except ValueError:
            print(f"Erro: valor inválido ({resposta!r}). Tente novamente.")


def senha(mensagem: str) -> str:
    """Pergunta um texto oculto (senha), saindo limpo se o usuário cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
    """
    print()
    resposta = cast(
        "str | None", questionary.password(mensagem, style=_ESTILO).ask()
    )
    if resposta is None:
        sys.exit(0)
    return resposta


def selecionar(mensagem: str, escolhas: list[str]) -> str:
    """Pergunta uma escolha única entre `escolhas`, saindo limpo se cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
        escolhas: opções disponíveis para seleção.
    """
    print()
    resposta = cast(
        "str | None",
        questionary.select(mensagem, choices=escolhas, style=_ESTILO).ask(),
    )
    if resposta is None:
        sys.exit(0)
    return resposta


def pausar(mensagem: str) -> None:
    """Pausa a execução até o usuário apertar uma tecla, saindo limpo se cancelar.

    Args:
        mensagem: texto exibido enquanto aguarda.
    """
    print()
    resposta = cast(
        "bool | None",
        questionary.press_any_key_to_continue(message=mensagem, style=_ESTILO).ask(),
    )
    if resposta is None:
        sys.exit(0)


def imprimir_destacado(texto_a_exibir: str, cor: str, negrito: bool = True) -> None:
    """Imprime um texto com a cor indicada (ex.: banner, confirmação).

    Args:
        texto_a_exibir: texto a exibir — uma linha ou um bloco ASCII de
            várias linhas.
        cor: código hex da cor, tipicamente `COR_DESTAQUE`, `COR_SUCESSO` ou
            `COR_SECUNDARIA`.
        negrito: `False` para texto de contexto/segundo plano (ex.: mensagem
            de boas-vindas com `COR_SECUNDARIA`) — negrito reforçaria
            destaque, o oposto do efeito "apagado" buscado ali.
    """
    estilo = f"bold fg:{cor}" if negrito else f"fg:{cor}"
    questionary.print(texto_a_exibir, style=estilo)


def cabecalho_etapa(numero: int, total: int, titulo: str) -> None:
    """Imprime um separador "── Etapa N/total — título ──" antes de uma fase do wizard.

    Depois do banner de abertura (`_BANNER` em `wizard.py`), o fluxo do
    wizard virava prompt puro do `questionary` — sem nenhuma pista visual de
    onde uma etapa termina e a próxima começa, nem de quanto falta. Inspirado
    em `rich.rule` (regra horizontal com título centralizado): mesma ideia,
    sem trazer a dependência — reaproveita `imprimir_destacado`, que já é o
    único ponto deste módulo que fala com `questionary.print`, e a mesma
    `COR_DESTAQUE` do banner, para não criar uma segunda linguagem visual.

    `numero`/`total` contam checkpoints visíveis ao usuário, não
    necessariamente as 14 "etapas" documentadas por módulo em
    `docs/system_design_doc.md` — duas dessas etapas (escolher fonte +
    testar conexão; gerar skeletons + pausar para curadoria) acontecem
    dentro de uma única chamada de `cli/etapas/*.py` sem uma pergunta nova
    ao usuário entre elas, então compartilham um único cabeçalho.

    Args:
        numero: posição do checkpoint atual (1-indexado).
        total: número total de checkpoints do wizard.
        titulo: nome curto da etapa, ex. "Escolher escopos".
    """
    print()
    rotulo = f" Etapa {numero}/{total} — {titulo} "
    preenchimento = max(_LARGURA_CABECALHO_ETAPA - len(rotulo), 4)
    esquerda = "─" * (preenchimento // 2)
    direita = "─" * (preenchimento - preenchimento // 2)
    imprimir_destacado(f"{esquerda}{rotulo}{direita}", COR_DESTAQUE)


def linha_de_decisao(rotulo: str, valor: str) -> None:
    """Imprime uma linha "├─ rótulo valor" resumindo uma decisão do usuário.

    Inspirado no resumo em árvore do shell da Oxide (uma sequência de linhas
    "├─ Title ..." / "└─ Deploy ...", cada uma ecoando uma pergunta já
    respondida). Lá o bloco é fechado e contíguo — todas as perguntas são
    feitas em sequência, sem nada entre elas — por isso faz sentido reservar
    `└─` para a última linha.

    Aqui não existe esse bloco fechado: as decisões reais do usuário (fonte,
    escopos, estratégia de amostragem, geradores, destino) estão espalhadas
    ao longo de 12 etapas do wizard, intercaladas por `cabecalho_etapa` e por
    blocos de processamento (extração, análise) que não são decisões — são o
    sistema trabalhando. Marcar uma dessas linhas com `└─` afirmaria "essa
    foi a última decisão", o que só é verdade por acaso, na hora em que ela
    é impressa — a próxima decisão real pode vir só depois de duas etapas de
    processamento. Por isso todo item usa sempre `├─`: um marcador honesto
    de "isto foi uma escolha sua", sem fingir uma árvore fechada que a
    interação real não tem.

    Reaproveita `imprimir_destacado`/`COR_DESTAQUE` — a mesma cor do banner
    e de `cabecalho_etapa` — para não introduzir uma 2ª linguagem visual
    concorrente só para marcar decisões.

    Args:
        rotulo: nome curto da decisão, ex. "Fonte".
        valor: resposta escolhida pelo usuário, ex. "PostgreSQL".
    """
    imprimir_destacado(f"├─ {rotulo} {valor}", COR_DESTAQUE)


def confirmar(mensagem: str, default: bool = True) -> bool:
    """Pergunta confirmação sim/não, saindo limpo se o usuário cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
        default: resposta pré-selecionada quando o usuário só aperta Enter.
    """
    print()
    resposta = cast(
        "bool | None",
        questionary.confirm(mensagem, default=default, style=_ESTILO).ask(),
    )
    if resposta is None:
        sys.exit(0)
    return resposta


def escolher_multiplos(mensagem: str, escolhas: list[str]) -> list[str]:
    """Checkbox com filtro por digitação — permite escolher um ou vários.

    Listas longas ficam difíceis de rolar em terminais pequenos; a forma
    rápida de achar um item é digitar parte do nome pra filtrar em vez de
    navegar pelas setas. Sai limpo se o usuário cancelar ou não marcar nada.

    Args:
        mensagem: pergunta exibida ao usuário.
        escolhas: opções disponíveis para seleção.
    """
    print()
    selecionados = cast(
        "list[str] | None",
        questionary.checkbox(
            mensagem,
            style=_ESTILO,
            choices=escolhas,
            use_search_filter=True,
            use_jk_keys=False,
            instruction="(digite para filtrar, espaço marca, enter confirma)",
        ).ask(),
    )
    if not selecionados:
        sys.exit(0)
    return selecionados


@contextmanager
def ampulheta(mensagem: str) -> Generator[None, None, None]:
    """Anima uma ampulheta virando ao lado da mensagem enquanto o bloco roda.

    Roda numa thread separada porque a chamada protegida dentro do `with` é
    síncrona/bloqueante — sem isso não haveria como atualizar o quadro
    enquanto se espera a resposta (ex.: teste de conexão, análise).

    Args:
        mensagem: texto exibido ao lado do ícone.
    """
    print()
    parar = threading.Event()

    def _animar() -> None:
        for quadro in itertools.cycle(_QUADROS_AMPULHETA):
            if parar.is_set():
                return
            print(f"\r\x1b[K{quadro} {mensagem}", end="", flush=True)
            time.sleep(0.3)

    thread = threading.Thread(target=_animar, daemon=True)
    thread.start()
    try:
        yield
    finally:
        parar.set()
        thread.join()


class Progresso(NamedTuple):
    """Trio de callbacks devolvido por `progresso_paralelo`.

    `NamedTuple`, não uma tupla posicional crua — os três campos têm
    papéis bem diferentes (um alimenta `progresso=`, outro
    `ao_conhecer_total=`, outro `inicio=`); nomear evita desempacotamento
    por posição num `tuple[Callable, Callable, Callable]` sem pistas do que
    é cada um.
    """

    callback: Callable[[str], None]
    definir_total: Callable[[int], None]
    inicio: Callable[[str], None]


def progresso_paralelo(mensagem_base: str, total: int | None = None) -> Progresso:
    """Devolve os callbacks de progresso, total e início usados sob paralelismo.

    Pensado para `.callback`/`.inicio` serem passados como `progresso=`/
    `inicio=` a `OrquestradorDeTabelas.extrair`/`aplicar_sobrescritas`. Não
    mostra tempo decorrido por item — a duração é do processo inteiro,
    exibida uma vez ao final pelo chamador.

    `.definir_total` existe para os casos em que o total só é conhecido
    depois de iniciada a chamada (ex.: `extrair`, que lista as tabelas de
    cada escopo internamente) — nesse caso, passe-o como `ao_conhecer_total=`
    e a fração "N/total" passa a valer a partir da 1ª chamada de progresso
    seguinte. Chamadores que já sabem o total (ex.: `aplicar_sobrescritas`,
    com `len(tabelas)` em mãos) simplesmente não usam `.definir_total`.

    `.callback` (conclusão) já chega serializado pela thread principal (ver
    `_executar_em_paralelo`), mas `.inicio` dispara de dentro de cada
    worker — pode chegar concorrentemente para itens diferentes. Por isso um
    `threading.Lock` interno protege tanto o conjunto de identificadores em
    andamento quanto a própria escrita no terminal, evitando linhas
    intercaladas quando dois workers chamam `.inicio`/`.callback` ao mesmo
    tempo.

    Args:
        mensagem_base: texto fixo exibido antes da contagem.
        total: número total de itens esperados, exibido como fração
            "N/total". Omitido quando ainda não é conhecido na criação.
    """
    print()
    lock = threading.Lock()
    concluidas = 0
    total_atual = total
    em_andamento: set[str] = set()

    def _definir_total(novo_total: int) -> None:
        nonlocal total_atual
        total_atual = novo_total

    def _renderizar() -> None:
        contagem = (
            f"{concluidas}/{total_atual}"
            if total_atual is not None
            else str(concluidas)
        )
        descricao = (
            f"em andamento: {', '.join(sorted(em_andamento))}"
            if em_andamento
            else "finalizando..."
        )
        print(
            f"\r\x1b[K{mensagem_base} ({contagem}) — {descricao}",
            end="",
            flush=True,
        )

    def _inicio(identificador: str) -> None:
        with lock:
            em_andamento.add(identificador)
            _renderizar()

    def _callback(identificador: str) -> None:
        nonlocal concluidas
        with lock:
            em_andamento.discard(identificador)
            concluidas += 1
            _renderizar()

    return Progresso(callback=_callback, definir_total=_definir_total, inicio=_inicio)

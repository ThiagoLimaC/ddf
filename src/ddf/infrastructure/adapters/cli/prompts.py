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


def imprimir_destacado(texto_a_exibir: str, cor: str) -> None:
    """Imprime um texto em negrito com a cor indicada (ex.: banner, confirmação).

    Args:
        texto_a_exibir: texto a exibir — uma linha ou um bloco ASCII de
            várias linhas.
        cor: código hex da cor, tipicamente `COR_DESTAQUE` ou `COR_SUCESSO`.
    """
    questionary.print(texto_a_exibir, style=f"bold fg:{cor}")


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
    """Par de callbacks devolvido por `progresso_paralelo`.

    `NamedTuple`, não uma tupla posicional crua — os dois campos têm
    papéis bem diferentes (um alimenta `progresso=`, o outro
    `ao_conhecer_total=`); nomear evita que um 3º callback futuro precise
    de desempacotamento por posição em `tuple[Callable, Callable, Callable]`.
    """

    callback: Callable[[str], None]
    definir_total: Callable[[int], None]


def progresso_paralelo(mensagem_base: str, total: int | None = None) -> Progresso:
    """Devolve (callback de progresso, callback para definir o total depois).

    Pensado para `.callback` ser passado como `progresso=` a
    `OrquestradorDeTabelas.extrair`/`aplicar_sobrescritas` — cada chamada já
    chega serializada pela thread principal (ver `_executar_em_paralelo`),
    sem necessidade de lock aqui. Não mostra tempo decorrido por item — a
    duração é do processo inteiro, exibida uma vez ao final pelo chamador.

    `.definir_total` existe para os casos em que o total só é conhecido
    depois de iniciada a chamada (ex.: `extrair`, que lista as tabelas de
    cada escopo internamente) — nesse caso, passe-o como `ao_conhecer_total=`
    e a fração "N/total" passa a valer a partir da 1ª chamada de progresso
    seguinte. Chamadores que já sabem o total (ex.: `aplicar_sobrescritas`,
    com `len(tabelas)` em mãos) simplesmente não usam `.definir_total`.

    Args:
        mensagem_base: texto fixo exibido antes da contagem.
        total: número total de itens esperados, exibido como fração
            "N/total". Omitido quando ainda não é conhecido na criação.
    """
    print()
    concluidas = 0
    total_atual = total

    def _definir_total(novo_total: int) -> None:
        nonlocal total_atual
        total_atual = novo_total

    def _callback(identificador: str) -> None:
        nonlocal concluidas
        concluidas += 1
        contagem = (
            f"{concluidas}/{total_atual}"
            if total_atual is not None
            else str(concluidas)
        )
        print(
            f"\r\x1b[K{mensagem_base} ({contagem}) — {identificador}",
            end="",
            flush=True,
        )

    return Progresso(callback=_callback, definir_total=_definir_total)

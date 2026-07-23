"""Helpers de interação do wizard — único módulo que importa `questionary`."""

import itertools
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import cast

import questionary

_QUADROS_AMPULHETA = ("⏳", "⌛")


def texto(mensagem: str, default: str = "") -> str:
    """Pergunta um texto livre, saindo limpo se o usuário cancelar (Ctrl+C/Esc).

    questionary captura o KeyboardInterrupt internamente e devolve None em
    vez de propagar — sem essa checagem, cada prompt cancelado quebraria em
    um TypeError diferente lá na frente (ex.: Path(None)), em vez de sair.

    Args:
        mensagem: pergunta exibida ao usuário.
        default: valor pré-preenchido no campo.
    """
    resposta = cast("str | None", questionary.text(mensagem, default=default).ask())
    if resposta is None:
        sys.exit(0)
    return resposta


def senha(mensagem: str) -> str:
    """Pergunta um texto oculto (senha), saindo limpo se o usuário cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
    """
    resposta = cast("str | None", questionary.password(mensagem).ask())
    if resposta is None:
        sys.exit(0)
    return resposta


def selecionar(mensagem: str, escolhas: list[str]) -> str:
    """Pergunta uma escolha única entre `escolhas`, saindo limpo se cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
        escolhas: opções disponíveis para seleção.
    """
    resposta = cast(
        "str | None", questionary.select(mensagem, choices=escolhas).ask()
    )
    if resposta is None:
        sys.exit(0)
    return resposta


def caminho(mensagem: str, default: str = "") -> str:
    """Pergunta um caminho de arquivo/diretório, com autocompletar do shell.

    Args:
        mensagem: pergunta exibida ao usuário.
        default: valor pré-preenchido no campo.
    """
    resposta = cast("str | None", questionary.path(mensagem, default=default).ask())
    if resposta is None:
        sys.exit(0)
    return resposta


def pausar(mensagem: str) -> None:
    """Pausa a execução até o usuário apertar uma tecla.

    Args:
        mensagem: texto exibido enquanto aguarda.
    """
    questionary.press_any_key_to_continue(message=mensagem).ask()


def confirmar(mensagem: str, default: bool = True) -> bool:
    """Pergunta confirmação sim/não, saindo limpo se o usuário cancelar.

    Args:
        mensagem: pergunta exibida ao usuário.
        default: resposta pré-selecionada quando o usuário só aperta Enter.
    """
    resposta = cast(
        "bool | None", questionary.confirm(mensagem, default=default).ask()
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
    selecionados = cast(
        "list[str] | None",
        questionary.checkbox(
            mensagem,
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


def progresso_paralelo(mensagem_base: str, total: int) -> Callable[[str], None]:
    """Devolve um callback de progresso para as fases paralelas do wizard.

    Pensado para ser passado como `progresso=` a `OrquestradorDeTabelas.
    extrair`/`aplicar_sobrescritas` — cada chamada já chega serializada pela
    thread principal (ver `_executar_em_paralelo`), sem necessidade de lock
    aqui.

    Args:
        mensagem_base: texto fixo exibido antes da contagem.
        total: número total de itens esperados, para a fração "N/total".
    """
    concluidas = 0

    def _callback(identificador: str) -> None:
        nonlocal concluidas
        concluidas += 1
        print(
            f"\r\x1b[K{mensagem_base} ({concluidas}/{total}) — {identificador}",
            end="",
            flush=True,
        )

    return _callback

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

# Spinner de texto puro (braille dots), não emoji — largura fixa, cor
# controlável via COR_*.
_QUADROS_AMPULHETA = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

COR_DESTAQUE = "#00d7ff"
COR_SUCESSO = "#58cd58"

# Erro é sempre fatal para o passo atual; aviso é informativo, não
# interrompe o fluxo — cores distintas evitam confundir as duas categorias.
COR_ERRO = "#ff5f5f"
COR_AVISO = "#d7af00"

# Texto de contexto/segundo plano (ex.: mensagem de boas-vindas), deliberadamente
# discreto perante COR_DESTAQUE/COR_SUCESSO.
COR_SECUNDARIA = "#6c6c6c"

# Resposta do usuário ecoada em COR_DESTAQUE, a mesma cor do banner.
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
            imprimir_destacado(
                f"Erro: valor inválido ({resposta!r}). Tente novamente.", COR_ERRO
            )


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
            imprimir_destacado(
                f"Erro: valor inválido ({resposta!r}). Tente novamente.", COR_ERRO
            )


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
        questionary.select(
            mensagem,
            choices=escolhas,
            style=_ESTILO,
            instruction="(setas para navegar, enter confirma)\n",
        ).ask(),
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


def imprimir_destacado(
    texto_a_exibir: str, cor: str | None, negrito: bool = True, end: str = "\n"
) -> None:
    r"""Imprime um texto com a cor indicada (ex.: banner, confirmação).

    `cor=None` reproduz o token `question` padrão do `questionary` (bold,
    sem `fg`). `end` permite compor uma linha bicolor em duas chamadas
    consecutivas, já que `questionary.print` só aceita um `style` por vez.

    Args:
        texto_a_exibir: texto a exibir — uma linha ou um bloco ASCII de
            várias linhas.
        cor: código hex da cor (`COR_DESTAQUE`, `COR_SUCESSO`,
            `COR_SECUNDARIA`...) ou `None` para a cor padrão do terminal.
        negrito: `False` para texto de contexto/segundo plano (ex.: mensagem
            de boas-vindas com `COR_SECUNDARIA`).
        end: terminador da linha; só muda ao compor uma linha bicolor (ver
            `linha_de_decisao`).
    """
    partes = []
    if negrito:
        partes.append("bold")
    if cor is not None:
        partes.append(f"fg:{cor}")
    estilo = " ".join(partes)
    questionary.print(texto_a_exibir, style=estilo, end=end)


def cabecalho_etapa(numero: int, total: int, titulo: str) -> None:
    """Imprime "└─ Etapa N/total — título" antes de uma fase do wizard.

    `numero`/`total` contam checkpoints visíveis ao usuário, não
    necessariamente as 14 "etapas" documentadas por módulo em
    `docs/system_design_doc.md` — etapas sem pergunta nova ao usuário entre
    si (ex.: escolher fonte + testar conexão) compartilham um único
    cabeçalho.

    Args:
        numero: posição do checkpoint atual (1-indexado).
        total: número total de checkpoints do wizard.
        titulo: nome curto da etapa, ex. "Escolher escopos".
    """
    print()
    imprimir_destacado(f"└─ Etapa {numero}/{total} — {titulo}", COR_DESTAQUE)


def linha_de_decisao(rotulo: str, valor: str, ultimo: bool = False) -> None:
    """Imprime uma linha "├─ rótulo valor" (ou "└─", se `ultimo`) resumindo uma decisão.

    `├─` é o padrão: a maior parte do wizard não forma um bloco fechado de
    decisões (elas se espalham por várias etapas, intercaladas por
    `cabecalho_etapa` e processamento) — `└─` só se aplica quando não há
    mais nenhuma linha de decisão logo em seguida sem processamento entre
    elas. Hoje só `conectar()` (Fonte/Host/Porta/Usuário/Senha em sequência
    contígua) usa `ultimo=True`, na última linha (Senha).

    Conector e rótulo saem sem cor (`cor=None`, o mesmo `"bold"` sem `fg`
    do token `question` padrão do `questionary`), imitando visualmente uma
    pergunta já feita. Valor sai em `COR_DESTAQUE`, a mesma cor que
    `_ESTILO` usa pra sobrescrever o token `answer` (a resposta ecoada pelo
    `questionary`).

    Args:
        rotulo: nome curto da decisão, ex. "Fonte".
        valor: resposta escolhida pelo usuário, ex. "PostgreSQL".
        ultimo: `True` fecha um bloco contíguo de decisões com `└─` em vez
            de `├─`.
    """
    conector = "└─" if ultimo else "├─"
    imprimir_destacado(conector, None, end=" ")
    imprimir_destacado(rotulo, None, end=" ")
    imprimir_destacado(valor, COR_DESTAQUE)


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
            # Mesma técnica de `selecionar()`: "\n" no fim da instrução, não
            # um print à parte — ver o comentário lá para o porquê.
            instruction="(digite para filtrar, espaço marca, enter confirma)\n",
        ).ask(),
    )
    if not selecionados:
        sys.exit(0)
    return selecionados


@contextmanager
def ampulheta(mensagem: str) -> Generator[None, None, None]:
    """Anima um spinner de braille ao lado da mensagem enquanto o bloco roda.

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
            time.sleep(0.08)

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


# Retângulo vertical cheio/vazio (U+25AE/U+25AF) — `▯` já é um contorno (só
# a borda desenhada, o miolo é o glifo "vazio" do próprio terminal), então
# o segmento não-concluído nunca pinta um fundo sólido por cima do
# terminal.
_BLOCO_CHEIO = "▮"
_BLOCO_VAZIO = "▯"

_ANSI_RESET = "\x1b[0m"


def _cor_ansi_truecolor(cor_hex: str) -> str:
    r"""Converte `#rrggbb` numa sequência ANSI truecolor de foreground.

    `_barra()` escreve direto via `print`/`\x1b[K`, não via
    `questionary.print` — não há `Style` do `prompt_toolkit` disponível
    naquele ponto, então a cor é aplicada manualmente.

    Args:
        cor_hex: cor no formato `#rrggbb` (ex.: `COR_SUCESSO`).
    """
    r, g, b = (int(cor_hex[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


def progresso_paralelo(mensagem_base: str, total: int | None = None) -> Progresso:
    r"""Devolve (callback de progresso, callback para definir o total depois).

    Pensado para `.callback` ser passado como `progresso=` a
    `OrquestradorDeTabelas.extrair`/`aplicar_sobrescritas` — cada chamada já
    chega serializada pela thread principal, sem necessidade de lock aqui.

    Desenha 3 linhas fixas — "mensagem (N/total)", uma linha em branco e uma
    barra de retângulos (`▮▮▮▯▯▯`) — sempre subindo até a 1ª linha antes de
    limpar e reescrever as 3, o que funciona mesmo com largura variável
    porque `\\x1b[K` limpa o resto da linha antes de escrever. A barra
    recalcula a própria largura a cada redesenho, pra terminar sob o `)` de
    "mensagem (N/total)" mesmo com a contagem crescendo em dígitos
    (`"(1/122)"` → `"(121/122)"`).

    Preenchido em `COR_DESTAQUE` (progresso em andamento, não `COR_SUCESSO`)
    e vazio em `COR_SECUNDARIA`.

    `.definir_total` existe para quando o total só é conhecido depois de
    iniciada a chamada (ex.: `extrair`, que lista as tabelas de cada escopo
    internamente) — a barra é desenhada assim que ele for chamado. Chamadores
    que já sabem o total (ex.: `aplicar_sobrescritas`) não precisam dele; a
    barra inicial (0/total) já é desenhada aqui.

    Args:
        mensagem_base: texto fixo exibido antes da contagem.
        total: número total de itens esperados, exibido como fração
            "N/total". Omitido quando ainda não é conhecido na criação.
    """
    print()
    concluidas = 0
    total_atual = total
    ja_desenhou = False

    def _barra(largura: int) -> str:
        preenchidos = (
            round(largura * concluidas / total_atual) if total_atual else 0
        )
        vazios = largura - preenchidos
        segmentos = [f"{_cor_ansi_truecolor(COR_DESTAQUE)}{_BLOCO_CHEIO}"] * preenchidos
        segmentos += [f"{_cor_ansi_truecolor(COR_SECUNDARIA)}{_BLOCO_VAZIO}"] * vazios
        return "".join(segmentos) + _ANSI_RESET

    def _desenhar() -> None:
        nonlocal ja_desenhou
        contagem = (
            f"{concluidas}/{total_atual}"
            if total_atual is not None
            else str(concluidas)
        )
        linha_contagem = f"{mensagem_base} ({contagem})"
        if ja_desenhou:
            print("\x1b[2A", end="")
        print(f"\r\x1b[K{linha_contagem}")
        print("\r\x1b[K")
        print(f"\r\x1b[K{_barra(len(linha_contagem))}", end="", flush=True)
        ja_desenhou = True

    def _definir_total(novo_total: int) -> None:
        nonlocal total_atual
        total_atual = novo_total
        _desenhar()

    def _callback(identificador: str) -> None:
        nonlocal concluidas
        concluidas += 1
        _desenhar()

    if total_atual is not None:
        _desenhar()

    return Progresso(callback=_callback, definir_total=_definir_total)


_LARGURA_BARRA_INDETERMINADA = 12
_TAMANHO_BLOCO_INDETERMINADO = 3


@contextmanager
def barra_indeterminada(mensagem: str) -> Generator[None, None, None]:
    r"""Anima um trecho de retângulos "correndo" ao lado da mensagem, sem N/total.

    Mesma estrutura de `ampulheta` (thread separada, `\r\x1b[K` redesenha a
    linha), pra operações sem um total real por item a contar (ex.:
    `analise.py::analisar`, que roda `compor()` numa única chamada opaca).

    Args:
        mensagem: texto exibido ao lado da barra.
    """
    print()
    parar = threading.Event()

    def _quadro(posicao: int) -> str:
        segmentos = [_BLOCO_VAZIO] * _LARGURA_BARRA_INDETERMINADA
        for deslocamento in range(_TAMANHO_BLOCO_INDETERMINADO):
            indice = (posicao + deslocamento) % _LARGURA_BARRA_INDETERMINADA
            segmentos[indice] = _BLOCO_CHEIO
        return "".join(segmentos)

    def _animar() -> None:
        posicao = 0
        while not parar.is_set():
            barra = (
                f"{_cor_ansi_truecolor(COR_DESTAQUE)}{_quadro(posicao)}{_ANSI_RESET}"
            )
            print(f"\r\x1b[K{barra} {mensagem}", end="", flush=True)
            posicao = (posicao + 1) % _LARGURA_BARRA_INDETERMINADA
            time.sleep(0.08)

    thread = threading.Thread(target=_animar, daemon=True)
    thread.start()
    try:
        yield
    finally:
        parar.set()
        thread.join()

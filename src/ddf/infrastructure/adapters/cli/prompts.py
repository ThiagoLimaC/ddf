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

# Braille dots (U+2800, bloco "Braille Patterns") — mesmo padrão default de
# `rich.spinner`/`cli-spinners` (Sindre Sorhus), não emoji: glifo de texto
# monoespaçado, largura fixa e cor controlável via COR_*, ao contrário de um
# emoji real (ampulheta ⏳/⌛ antiga), que tem largura variável entre fontes
# e ignora `COR_*`. Mesmo critério já usado para preferir `▮`/`▯` a `█`/`░`
# (ver comentário perto de `_BLOCO_CHEIO`).
_QUADROS_AMPULHETA = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

COR_DESTAQUE = "#00d7ff"

# Verde pastel/fosco — não o verde puro `#00d700` usado antes, que destoava
# do resto da paleta (todas as outras cores são tons "quebrados", não um
# canal isolado no extremo). Pedido explícito do usuário: verde
# "extremamente marcante e chamativo" demais para o tom geral da CLI.
COR_SUCESSO = "#58cd58"

# Vermelho/âmbar do mesmo cubo xterm 256 usado no resto da paleta (steps
# 0x00/0x87/0xd7/0xff) — erro é sempre fatal para o passo atual (sys.exit ou
# retry obrigatório); aviso é informativo, não interrompe o fluxo. Cores
# distintas para não confundir as duas categorias visualmente.
COR_ERRO = "#ff5f5f"
COR_AVISO = "#d7af00"

# Cinza fosco/dimmed para texto de contexto (ex.: mensagem de boas-vindas),
# em segundo plano deliberado perante COR_DESTAQUE/COR_SUCESSO. Mesmo tom
# usado por `gh` para texto secundário (`Gray()`, ANSI 256 cor 242 ≈ RGB
# 108,108,108) — legível sobre fundo escuro ou claro, sem competir com as
# cores vivas reservadas a decisões e resultados.
COR_SECUNDARIA = "#6c6c6c"

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

    `cor=None` imprime sem sobrescrever a cor do terminal — equivalente ao
    token `question` do tema padrão do `questionary` (só `"bold"`, sem `fg`,
    ver `linha_de_decisao`). `end` existe para compor uma linha com mais de
    uma cor: `questionary.print` (via `prompt_toolkit.print_formatted_text`)
    só aceita um `style` por chamada, então uma linha bicolor é duas
    chamadas consecutivas, a 1ª com `end=" "` ou `end=""`.

    Args:
        texto_a_exibir: texto a exibir — uma linha ou um bloco ASCII de
            várias linhas.
        cor: código hex da cor, tipicamente `COR_DESTAQUE`, `COR_SUCESSO` ou
            `COR_SECUNDARIA`. `None` para não sobrescrever a cor padrão do
            terminal.
        negrito: `False` para texto de contexto/segundo plano (ex.: mensagem
            de boas-vindas com `COR_SECUNDARIA`) — negrito reforçaria
            destaque, o oposto do efeito "apagado" buscado ali.
        end: terminador da linha, repassado a `print_formatted_text`. Só
            vale a pena mudar para compor uma linha com mais de uma cor
            (ver `linha_de_decisao`); no resto do módulo cada chamada é uma
            linha inteira, então o padrão `"\\n"` basta.
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

    Depois do banner de abertura (`_BANNER` em `wizard.py`), o fluxo do
    wizard virava prompt puro do `questionary` — sem nenhuma pista visual de
    onde uma etapa termina e a próxima começa, nem de quanto falta. Usa o
    mesmo vocabulário de conector de árvore do shell da Oxide que motivou
    `linha_de_decisao` — sem régua horizontal decorativa, só o símbolo que
    introduz o próximo bloco. Reaproveita `imprimir_destacado`, único ponto
    deste módulo que fala com `questionary.print`, e a mesma `COR_DESTAQUE`
    do banner, para não criar uma segunda linguagem visual.

    `└─` aqui não é "último item de uma lista" (como `linha_de_decisao`
    evita propositalmente) — é o marcador de entrada de um bloco novo e
    isolado: cada etapa aparece sozinha, nunca como parte de uma sequência
    visualmente contígua de cabeçalhos, então não há ambiguidade de "isso é
    a última etapa?" para desfazer.

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
    imprimir_destacado(f"└─ Etapa {numero}/{total} — {titulo}", COR_DESTAQUE)


def linha_de_decisao(rotulo: str, valor: str, ultimo: bool = False) -> None:
    """Imprime uma linha "├─ rótulo valor" (ou "└─", se `ultimo`) resumindo uma decisão.

    Inspirado no resumo em árvore do shell da Oxide (uma sequência de linhas
    "├─ Title ..." / "└─ Deploy ...", cada uma ecoando uma pergunta já
    respondida). Lá o bloco é fechado e contíguo — todas as perguntas são
    feitas em sequência, sem nada entre elas — por isso faz sentido reservar
    `└─` para a última linha: é o marcador de "esse bloco de decisões
    terminou aqui", não de "última decisão do fluxo inteiro".

    Na maior parte do wizard esse bloco fechado não existe: as decisões
    reais do usuário (escopos, estratégia de amostragem, geradores, destino)
    estão espalhadas ao longo de várias etapas, intercaladas por
    `cabecalho_etapa` e por blocos de processamento (extração, análise) que
    não são decisões — são o sistema trabalhando. Marcar uma dessas linhas
    com `└─` afirmaria "esse bloco de decisões terminou", o que não é
    verdade ali — a próxima linha de decisão pode vir logo em seguida, sem
    nenhum processamento entre elas. Por isso o padrão é `ultimo=False`
    (sempre `├─`): um marcador honesto de "isto foi uma escolha sua", sem
    fingir uma árvore fechada que a interação real não tem.

    A etapa de conexão (`cli/etapas/extracao.py::conectar`) é a exceção
    real, não uma segunda regra: Fonte/Host/Porta/[Banco]/Usuário/Senha são
    perguntadas em sequência contígua, sem nenhum processamento entre elas —
    exatamente a condição que a regra acima já previa para justificar
    `└─`. Ali o último `linha_de_decisao` da sequência (Senha) passa
    `ultimo=True`. Continua sendo a mesma regra ("`└─` fecha um bloco
    contíguo de decisões"), só que essa é a primeira etapa onde a condição
    é verdadeira.

    O conector (`├─`/`└─`) usa a mesma cor do rótulo, não `COR_DESTAQUE` —
    aqui (diferente de `cabecalho_etapa`, que é estrutura do wizard) o
    conector faz parte da árvore de decisão em si, então acompanha o
    rótulo. O rótulo (`Fonte`, `Host`, ...) e o valor (`PostgreSQL`,
    `db.exemplo.com`, ...) imitam visualmente a pergunta original e a
    resposta que o usuário deu a ela:

    - Conector e rótulo → estilo do token `question` do tema padrão do `questionary`
      (`site-packages/questionary/constants.py::DEFAULT_STYLE`), que nunca
      foi sobrescrito por `_ESTILO` neste módulo: `"bold"`, sem `fg` — ou
      seja, a cor de "uma pergunta já feita" aqui é literalmente a cor
      padrão do terminal, só em negrito. `cor=None` em `imprimir_destacado`
      reproduz exatamente isso, em vez de inventar um hex novo.
    - Valor → `COR_DESTAQUE`, a mesma cor que `_ESTILO` já usa para
      sobrescrever o token `answer` do `questionary` (a resposta ecoada ao
      lado da pergunta) — não a cor default do `answer` do tema
      (`#FF9D00`), que este projeto nunca usa.

    Args:
        rotulo: nome curto da decisão, ex. "Fonte".
        valor: resposta escolhida pelo usuário, ex. "PostgreSQL".
        ultimo: `True` fecha um bloco contíguo de decisões com `└─` em vez
            de `├─`. Só faz sentido quando não há mais nenhuma linha de
            decisão logo em seguida, sem processamento entre elas — ver
            `conectar()` para o único caso de uso hoje.
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

    Nome mantido por compatibilidade com o resto do módulo/chamadores —
    era literalmente uma ampulheta (⏳/⌛) até esta função trocar de emoji
    para o spinner de texto puro (ver `_QUADROS_AMPULHETA`).

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


# Retângulo vertical cheio/vazio (U+25AE/U+25AF, bloco "Geometric Shapes" do
# Unicode) — não os blocos de textura (`█`/`░`) usados antes. `▯` já É um
# contorno (só a borda do retângulo é desenhada, o miolo é o glifo "vazio"
# do próprio terminal), então o segmento não-concluído nunca pinta um fundo
# sólido cinza por cima do fundo real do terminal — pedido explícito do
# usuário ao revisar a 1ª versão desta barra. Ambos amplamente suportados em
# fontes monoespaçadas de terminal (mesmo bloco geométrico de `■`/`□`/`▪`,
# já cobertos por qualquer fonte com bom suporte a Unicode — DejaVu Sans
# Mono, Cascadia Code, JetBrains Mono, etc.).
_BLOCO_CHEIO = "▮"
_BLOCO_VAZIO = "▯"

_ANSI_RESET = "\x1b[0m"


def _cor_ansi_truecolor(cor_hex: str) -> str:
    r"""Converte `#rrggbb` numa sequência ANSI truecolor de foreground.

    `_barra()` escreve direto via `print`/`\x1b[K`, não via
    `questionary.print` — não há `Style` do `prompt_toolkit` disponível
    naquele ponto, então a cor é aplicada manualmente com o mesmo esquema
    truecolor (`ESC[38;2;r;g;bm`) que os terminais modernos já entendem para
    os hex de `COR_SUCESSO`/`COR_SECUNDARIA` usados no resto do módulo.

    Args:
        cor_hex: cor no formato `#rrggbb` (ex.: `COR_SUCESSO`).
    """
    r, g, b = (int(cor_hex[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


def progresso_paralelo(mensagem_base: str, total: int | None = None) -> Progresso:
    r"""Devolve (callback de progresso, callback para definir o total depois).

    Pensado para `.callback` ser passado como `progresso=` a
    `OrquestradorDeTabelas.extrair`/`aplicar_sobrescritas` — cada chamada já
    chega serializada pela thread principal (ver `_executar_em_paralelo`),
    sem necessidade de lock aqui. Não mostra tempo decorrido por item — a
    duração é do processo inteiro, exibida uma vez ao final pelo chamador.

    Desenha 3 linhas fixas — "mensagem (N/total)", uma linha em branco e uma
    barra de retângulos (`▮▮▮▯▯▯`, inspirada no shell da Oxide) —
    reescritas no lugar a cada chamada. Substitui uma tentativa anterior de
    mostrar o identificador do item "em andamento": sob paralelismo real
    (~100+ tabelas), a lista de identificadores crescia até quebrar em
    várias linhas do terminal, e `\\r`/`\\x1b[K` não alcançam linhas acima da
    atual — gerava um log cascateado (ver
    `plan/registry-plan/issue-116-ajustes-de-ux-no-wizard.md`). O redesenho
    (sempre sobe até a 1ª linha, limpa e reescreve as 3) é seguro mesmo com
    largura variável, porque `\\x1b[K` limpa o resto da linha inteira antes
    de escrever — não depende de a barra ter sempre o mesmo tamanho.

    A barra tem a mesma largura, em colunas, da linha "mensagem (N/total)"
    acima dela — termina exatamente sob o `)` de fechamento, não um número
    fixo de segmentos independente do texto. Como a contagem cresce em
    dígitos ao longo da execução (`"(1/122)"` → `"(121/122)"`), a barra
    recalcula a largura a cada redesenho.

    O segmento preenchido usa `COR_DESTAQUE` (o mesmo ciano do banner, de
    `cabecalho_etapa` e do valor ecoado em `linha_de_decisao` — não
    `COR_SUCESSO`: a barra mostra progresso em andamento, não um resultado
    concluído) e o vazio `COR_SECUNDARIA` (o mesmo cinza fosco de texto de
    segundo plano). Cada retângulo é um segmento discreto, unido direto ao
    vizinho (sem espaçador) — não há mais um único caractere de transição
    (`_SEPARADOR_BARRA`): com `▮`/`▯` como glifos individuais já estreitos, a
    separação visual entre segmentos já nasce da própria
    textura, sem precisar de um caractere extra dedicado a isso.

    `.definir_total` existe para os casos em que o total só é conhecido
    depois de iniciada a chamada (ex.: `extrair`, que lista as tabelas de
    cada escopo internamente) — nesse caso, passe-o como `ao_conhecer_total=`
    e a barra é desenhada assim que ele for chamado, antes do 1º item
    concluído. Chamadores que já sabem o total (ex.: `aplicar_sobrescritas`,
    com `len(tabelas)` em mãos) não usam `.definir_total` — a barra inicial
    (0/total) já é desenhada aqui.

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
        # Cor embutida em cada segmento (não uma sequência ANSI só na
        # transição) porque os retângulos são unidos direto, sem espaçador —
        # um único par de blocos "cor + N repetições" como antes deixaria
        # sem cor definida qualquer separador entre segmentos.
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
    linha) — a diferença é só visual: usa a mesma textura de retângulos
    (`▮`/`▯`, `COR_DESTAQUE`) de `progresso_paralelo`, em vez do ícone de
    ampulheta, para operações sem um total real por item a contar (ex.:
    `analise.py::analisar`, que roda `compor()` numa única chamada opaca,
    sem callback por Analisador — ver `ddf/pipeline/compor.py`). Uma fração
    "N/total" ali mentiria um progresso que o código não tem como medir;
    esta barra corre sem prometer conclusão, só sinaliza "ainda vivo".

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

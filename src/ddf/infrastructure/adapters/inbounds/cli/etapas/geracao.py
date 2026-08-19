"""Etapas 12-14 do wizard: destino dos artefatos, confirmação e execução."""

import sys
from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.inbounds.cli import prompts
from ddf.infrastructure.adapters.inbounds.cli.registro.geradores import (
    GERADORES_REGISTRADOS,
)
from ddf.pipeline.etapas.geracao import ResultadoDeGerador
from ddf.pipeline.etapas.geracao import (
    executar_geradores as pipeline_executar_geradores,
)


def confirmar_execucao(nomes_geradores: list[str], destino: Path) -> None:
    """Etapa 13: mostra um resumo do que será gerado e confirma antes de executar."""
    lista = ", ".join(nomes_geradores)
    confirmado = prompts.confirmar(
        f"Gerar {lista} em subpastas dentro de '{destino.resolve()}'?"
    )
    if not confirmado:
        sys.exit(0)


def _exibir_resultado(item: ResultadoDeGerador) -> bool:
    """Exibe avisos e sucesso/falha de um Gerador. Devolve True se houve falha.

    Args:
        item: nome, destino e Resultado da execução de um Gerador.

    Returns:
        True se o Gerador falhou, False se teve sucesso.
    """
    for aviso in item.resultado.avisos:
        prompts.imprimir_destacado(f"▲ {aviso.mensagem}", prompts.COR_AVISO)
    if isinstance(item.resultado, Falha):
        prompts.imprimir_destacado(
            f"Falha em '{item.nome}': {item.resultado.erro}", prompts.COR_ERRO
        )
        return True
    prompts.imprimir_destacado(
        f"✓ '{item.nome}': artefato escrito em '{item.destino.resolve()}'.",
        prompts.COR_SUCESSO,
    )
    return False


def executar_geradores(
    nomes_geradores: list[str], banco_analisado: BancoAnalisado, destino: Path
) -> None:
    """Etapa 14: executa cada Gerador escolhido, protegido por executar_com_seguranca.

    Cada Gerador escreve na sua própria subpasta (`destino/<slug>`), mesmo
    quando só um é escolhido — evita misturar artefatos de Geradores
    diferentes no mesmo diretório quando mais de um é escolhido na mesma
    execução.

    Avisos são exibidos como uma linha "▲ mensagem" logo acima da mensagem
    de sucesso/falha daquele Gerador — mesmo padrão de `_construir_
    percentual_de_linhas` (registro/estrategias.py) — em vez do bloco
    agrupado por origem de `avisos.exibir_avisos`: a posição já deixa claro
    a qual artefato o aviso pertence, sem precisar repetir o nome do
    Gerador numa linha "[origem] N aviso(s)". A exibição é incremental —
    um Gerador por vez, à medida que cada um termina — não em lote ao
    final de todos.

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
        banco_analisado: banco curado com as métricas já calculadas.
        destino: diretório raiz onde os artefatos são escritos.
    """
    houve_falha = False

    def _progresso(item: ResultadoDeGerador) -> None:
        nonlocal houve_falha
        if _exibir_resultado(item):
            houve_falha = True

    print()
    pipeline_executar_geradores(
        nomes_geradores,
        GERADORES_REGISTRADOS,
        banco_analisado,
        destino,
        progresso=_progresso,
    )

    if houve_falha:
        sys.exit(1)

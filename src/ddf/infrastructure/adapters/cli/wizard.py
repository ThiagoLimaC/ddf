"""Wizard interativo do ddf — fluxo completo via click + questionary."""

import sys
from pathlib import Path

import click

from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.etapas import analise, curadoria, extracao, geracao
from ddf.infrastructure.adapters.orchestrator.orquestrador_paralelo import (
    OrquestradorParalelo,
)

_BANNER = r"""
      __      __     ___
     /\ \    /\ \  /'___\
     \_\ \   \_\ \/\ \__/
     /'_` \  /'_` \ \ ,__\
    /\ \L\ \/\ \L\ \ \ \_/
    \ \___,_\ \___,_\ \_\
     \/__,_ /\/__,_ /\/_/

   data dictionary framework
   by: Thiago Lima
"""


@click.command()
def executar() -> None:
    """Executa o wizard interativo do ddf, da conexão aos artefatos gerados."""
    prompts.imprimir_destacado(_BANNER, prompts.COR_DESTAQUE)
    configuracao = extracao.configurar_amostragem()
    extrator, escopos_disponiveis = extracao.conectar(configuracao)
    escopos = prompts.escolher_multiplos(
        "Escolha um ou mais escopos:", escopos_disponiveis
    )

    orquestrador = OrquestradorParalelo()
    tabelas = extracao.extrair(orquestrador, extrator, escopos)
    if not tabelas:
        print("Nenhuma tabela extraída com sucesso.")
        sys.exit(1)

    diretorio_overrides = Path(
        prompts.texto(
            "Diretório de overrides:", default="overrides", dica_limpar=True
        )
    ).expanduser()
    sobrescrita = curadoria.curar(orquestrador, diretorio_overrides, tabelas)

    banco_curado = curadoria.aplicar_sobrescritas(orquestrador, sobrescrita, tabelas)
    if not banco_curado.tabelas:
        print("Nenhuma tabela curada com sucesso.")
        sys.exit(1)

    nomes_geradores = analise.escolher_geradores()
    analisadores_ordenados = analise.validar_selecao(nomes_geradores)
    banco_analisado = analise.analisar(analisadores_ordenados, banco_curado)

    destino = Path(
        prompts.texto(
            "Diretório de destino dos artefatos:",
            default=geracao.sugerir_destino(nomes_geradores),
            dica_limpar=True,
        )
    ).expanduser()
    geracao.confirmar_execucao(nomes_geradores, destino)
    geracao.executar_geradores(nomes_geradores, banco_analisado, destino)


if __name__ == "__main__":
    executar()

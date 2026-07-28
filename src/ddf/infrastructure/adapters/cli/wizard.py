"""Wizard interativo do ddf — fluxo completo via click + questionary."""

import sys
from collections.abc import Sequence
from pathlib import Path

import click

from ddf.infrastructure.adapters.cli import avisos, prompts
from ddf.infrastructure.adapters.cli.etapas import analise, curadoria, extracao, geracao
from ddf.infrastructure.adapters.cli.registro import descoberta
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


def _sair_se_vazio(itens: Sequence[object], mensagem: str) -> None:
    """Imprime `mensagem` e sai com código 1 se `itens` estiver vazio.

    `OrquestradorParalelo.extrair`/`aplicar_sobrescritas` nunca devolvem
    Falha — falha individual de item vira Aviso, o lote inteiro sempre
    "tem sucesso" mesmo com 0 itens processados (ver docstring de ambos).
    Esta função é o único ponto que decide que um lote vazio não deve
    seguir para as etapas seguintes do wizard.
    """
    if not itens:
        print(mensagem)
        sys.exit(1)


@click.command()
def executar() -> None:
    """Executa o wizard interativo do ddf, da conexão aos artefatos gerados."""
    prompts.imprimir_destacado(_BANNER, prompts.COR_DESTAQUE)
    avisos.exibir_avisos(
        descoberta.descobrir_extratores() + descoberta.descobrir_geradores()
    )
    extrator, configuracao, escopos_disponiveis = extracao.conectar()
    escopos = prompts.escolher_multiplos(
        "Escolha um ou mais escopos:", escopos_disponiveis
    )
    extracao.configurar_amostragem(configuracao)

    orquestrador = OrquestradorParalelo()
    tabelas = extracao.extrair(orquestrador, extrator, escopos)
    _sair_se_vazio(tabelas, "Nenhuma tabela extraída com sucesso.")

    diretorio_overrides = Path(
        prompts.texto(
            "Diretório de overrides:", default="overrides", dica_limpar=True
        )
    ).expanduser()
    sobrescrita = curadoria.curar(orquestrador, diretorio_overrides, tabelas)

    banco_curado = curadoria.aplicar_sobrescritas(orquestrador, sobrescrita, tabelas)
    _sair_se_vazio(banco_curado.tabelas, "Nenhuma tabela curada com sucesso.")

    nomes_geradores = analise.escolher_geradores()
    analisadores_ordenados = analise.validar_selecao(nomes_geradores)
    banco_analisado = analise.analisar(analisadores_ordenados, banco_curado)

    destino = Path(
        prompts.texto(
            "Diretório de destino dos artefatos:",
            default="artefatos",
            dica_limpar=True,
        )
    ).expanduser()
    geracao.confirmar_execucao(nomes_geradores, destino)
    geracao.executar_geradores(nomes_geradores, banco_analisado, destino)


if __name__ == "__main__":
    executar()

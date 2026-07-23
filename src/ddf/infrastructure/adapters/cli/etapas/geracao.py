"""Etapas 12-14 do wizard: destino dos artefatos, confirmação e execução."""

import sys
from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import exibir_avisos
from ddf.infrastructure.adapters.cli.registro.geradores import GERADORES_REGISTRADOS
from ddf.pipeline.seguranca import executar_com_seguranca

_SUGESTOES_DE_DESTINO = {
    "Markdown": "markdown",
    "Dbt": "dbt",
    "ContextoDeIA": "contexto_de_ia",
}


def sugerir_destino(nomes_geradores: list[str]) -> str:
    """Sugere um destino específico do Gerador quando só um foi escolhido.

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
    """
    if len(nomes_geradores) != 1:
        return "artefatos"
    nome = nomes_geradores[0]
    return f"artefatos/{_SUGESTOES_DE_DESTINO.get(nome, nome.lower())}"


def confirmar_execucao(nomes_geradores: list[str], destino: Path) -> None:
    """Etapa 13: mostra um resumo do que será gerado e confirma antes de executar."""
    lista = ", ".join(nomes_geradores)
    confirmado = prompts.confirmar(f"Gerar {lista} em '{destino.resolve()}'?")
    if not confirmado:
        sys.exit(0)


def executar_geradores(
    nomes_geradores: list[str], banco_analisado: BancoAnalisado, destino: Path
) -> None:
    """Etapa 14: executa cada Gerador escolhido, protegido por executar_com_seguranca.

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
        banco_analisado: banco curado com as métricas já calculadas.
        destino: diretório onde os artefatos são escritos.
    """
    houve_falha = False
    for nome in nomes_geradores:
        gerador = GERADORES_REGISTRADOS[nome]
        resultado = executar_com_seguranca(
            nome, lambda: gerador(banco_analisado, destino)
        )
        exibir_avisos(resultado.avisos)
        if isinstance(resultado, Falha):
            print(f"Falha em '{nome}': {resultado.erro}")
            houve_falha = True
            continue
        print(f"'{nome}': artefato(s) escrito(s) em '{destino.resolve()}'.")

    if houve_falha:
        sys.exit(1)

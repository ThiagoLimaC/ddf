"""Etapas 12-14 do wizard: destino dos artefatos, confirmação e execução."""

import re
import sys
from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import exibir_avisos
from ddf.infrastructure.adapters.cli.registro.geradores import GERADORES_REGISTRADOS
from ddf.pipeline.seguranca import executar_com_seguranca

_LIMITE_PALAVRA = re.compile(r"(.)([A-Z][a-z]+)")
_LIMITE_SIGLA = re.compile(r"([a-z0-9])([A-Z])")


def _slugificar(nome: str) -> str:
    """Converte um nome de registro CamelCase em snake_case pra nome de pasta.

    Genérico — não depende de conhecer os nomes dos Geradores nativos de
    antemão, ao contrário de um dicionário fixo por nome. "ContextoDeIA"
    vira "contexto_de_ia", "Markdown" vira "markdown", sem exceção
    cadastrada à parte para nenhum dos dois.
    """
    com_separador_de_palavra = _LIMITE_PALAVRA.sub(r"\1_\2", nome)
    com_separador_de_sigla = _LIMITE_SIGLA.sub(r"\1_\2", com_separador_de_palavra)
    return com_separador_de_sigla.lower()


def sugerir_destino(nomes_geradores: list[str]) -> str:
    """Sugere um destino específico do Gerador quando só um foi escolhido.

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
    """
    if len(nomes_geradores) != 1:
        return "artefatos"
    return f"artefatos/{_slugificar(nomes_geradores[0])}"


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

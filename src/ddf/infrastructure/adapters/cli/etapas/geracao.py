"""Etapas 12-14 do wizard: destino dos artefatos, confirmação e execução."""

import re
import sys
from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
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


def confirmar_execucao(nomes_geradores: list[str], destino: Path) -> None:
    """Etapa 13: mostra um resumo do que será gerado e confirma antes de executar."""
    lista = ", ".join(nomes_geradores)
    confirmado = prompts.confirmar(
        f"Gerar {lista} em subpastas dentro de '{destino.resolve()}'?"
    )
    if not confirmado:
        sys.exit(0)


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
    Gerador numa linha "[origem] N aviso(s)".

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
        banco_analisado: banco curado com as métricas já calculadas.
        destino: diretório raiz onde os artefatos são escritos.
    """
    houve_falha = False
    for nome in nomes_geradores:
        gerador = GERADORES_REGISTRADOS[nome]
        destino_gerador = destino / _slugificar(nome)
        resultado = executar_com_seguranca(
            nome, lambda: gerador(banco_analisado, destino_gerador)
        )
        print()
        for aviso in resultado.avisos:
            prompts.imprimir_destacado(f"▲ {aviso.mensagem}", prompts.COR_AVISO)
        if isinstance(resultado, Falha):
            prompts.imprimir_destacado(
                f"Falha em '{nome}': {resultado.erro}", prompts.COR_ERRO
            )
            houve_falha = True
            continue
        prompts.imprimir_destacado(
            f"✓ '{nome}': artefato escrito em '{destino_gerador.resolve()}'.",
            prompts.COR_SUCESSO,
        )

    if houve_falha:
        sys.exit(1)

"""Etapas 9-11 do wizard: escolha de Geradores, validação e análise."""

import sys
import time

from ddf.domain.model.analysis import BancoAnalisado, iniciar_contexto
from ddf.domain.model.curation import BancoCurado
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import ou_sair
from ddf.infrastructure.adapters.cli.registro.analisadores import (
    ANALISADORES_REGISTRADOS,
)
from ddf.infrastructure.adapters.cli.registro.geradores import GERADORES_REGISTRADOS
from ddf.pipeline.compor import compor
from ddf.pipeline.validar_dependencias import validar_dependencias


def escolher_geradores() -> list[str]:
    """Etapa 9: escolhe um ou mais Geradores entre os registrados."""
    return prompts.escolher_multiplos(
        "Escolha um ou mais geradores:", list(GERADORES_REGISTRADOS.keys())
    )


def validar_selecao(nomes_geradores_escolhidos: list[str]) -> list[Analisador]:
    """Etapa 10: valida produz/requer, devolve os Analisadores em ordem de execução.

    Roda contra todos os Analisadores registrados (sempre executam todos,
    sem seleção do usuário) e só os Geradores que o usuário escolheu — um
    Gerador registrado mas não escolhido nunca bloqueia a validação.
    """
    geradores = {
        nome: GERADORES_REGISTRADOS[nome] for nome in nomes_geradores_escolhidos
    }
    resultado = validar_dependencias(ANALISADORES_REGISTRADOS, geradores)
    return ou_sair(resultado)


def analisar(
    analisadores_ordenados: list[Analisador], banco_curado: BancoCurado
) -> BancoAnalisado:
    """Etapa 11: roda os Analisadores via compor(), monta o BancoAnalisado.

    Avisos são exibidos como uma linha "▲ mensagem" logo acima da mensagem
    de sucesso — mesmo padrão de `geracao.py::executar_geradores` e de
    `_construir_percentual_de_linhas` (registro/estrategias.py) — em vez do
    bloco agrupado por origem de `avisos.exibir_avisos`.
    """
    contexto = iniciar_contexto(banco_curado)
    inicio = time.monotonic()
    with prompts.barra_indeterminada("Analisando..."):
        resultado = compor(*analisadores_ordenados)(contexto)
    print()
    print()
    for aviso in resultado.avisos:
        prompts.imprimir_destacado(f"▲ {aviso.mensagem}", prompts.COR_AVISO)
    if isinstance(resultado, Falha):
        prompts.imprimir_destacado(f"Erro: {resultado.erro}", prompts.COR_ERRO)
        sys.exit(1)
    banco_analisado = resultado.valor.analisado
    prompts.imprimir_destacado("✓ Análise concluída.", prompts.COR_SUCESSO)
    print(f"duração: {time.monotonic() - inicio:.0f}s")
    return banco_analisado

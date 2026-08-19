"""Etapas 9-11 do wizard: escolha de Geradores, validação e análise."""

import sys
import time

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.model.curation import BancoCurado
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.inbounds.cli import prompts
from ddf.infrastructure.adapters.inbounds.cli.avisos import ou_sair
from ddf.infrastructure.adapters.inbounds.cli.registro.analisadores import (
    ANALISADORES_REGISTRADOS,
)
from ddf.infrastructure.adapters.inbounds.cli.registro.geradores import (
    GERADORES_REGISTRADOS,
)
from ddf.pipeline.etapas import analise as pipeline_analise
from ddf.pipeline.etapas.validar_dependencias import validar_dependencias


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
    """Etapa 11: roda os Analisadores via pipeline.analise.analisar.

    Avisos são exibidos como uma linha "▲ mensagem" logo acima da mensagem
    de sucesso — mesmo padrão de `geracao.py::executar_geradores` e de
    `_construir_percentual_de_linhas` (registro/estrategias.py) — em vez do
    bloco agrupado por origem de `avisos.exibir_avisos`.
    """
    inicio = time.monotonic()
    with prompts.barra_indeterminada("Analisando..."):
        resultado = pipeline_analise.analisar(analisadores_ordenados, banco_curado)
    print()
    print()
    for aviso in resultado.avisos:
        prompts.imprimir_destacado(f"▲ {aviso.mensagem}", prompts.COR_AVISO)
    if isinstance(resultado, Falha):
        prompts.imprimir_destacado(f"Erro: {resultado.erro}", prompts.COR_ERRO)
        sys.exit(1)
    banco_analisado = resultado.valor
    prompts.imprimir_destacado("✓ Análise concluída.", prompts.COR_SUCESSO)
    print(f"duração: {time.monotonic() - inicio:.0f}s")
    return banco_analisado

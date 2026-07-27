"""Etapas 9-11 do wizard: escolha de Geradores, validação e análise."""

from ddf.domain.model.analysis import BancoAnalisado, iniciar_contexto
from ddf.domain.model.curation import BancoCurado
from ddf.domain.ports.analisador import Analisador
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import ou_sair
from ddf.infrastructure.adapters.cli.registro.analisadores import (
    ANALISADORES_REGISTRADOS,
)
from ddf.infrastructure.adapters.cli.registro.geradores import GERADORES_REGISTRADOS
from ddf.infrastructure.adapters.cli.validacao import validar_dependencias
from ddf.pipeline.compor import compor


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
    """Etapa 11: roda os Analisadores via compor(), monta o BancoAnalisado."""
    contexto = iniciar_contexto(banco_curado)
    with prompts.ampulheta("Analisando..."):
        resultado = compor(*analisadores_ordenados)(contexto)
    print()
    return ou_sair(resultado).analisado

"""Registro de Estratégias de amostragem disponíveis para o wizard da CLI."""

from collections.abc import Callable
from dataclasses import dataclass

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


@dataclass(frozen=True)
class EstrategiaRegistrada:
    """Uma EstrategiaDeAmostragem registrada, junto da função que a constrói."""

    classe_estrategia: type[EstrategiaDeAmostragem]
    construir: Callable[[], EstrategiaDeAmostragem]


ESTRATEGIAS_REGISTRADAS: dict[str, EstrategiaRegistrada] = {}


def registrar_estrategia(
    nome: str,
    classe_estrategia: type[EstrategiaDeAmostragem],
    construir: Callable[[], EstrategiaDeAmostragem],
    registro: dict[str, EstrategiaRegistrada] = ESTRATEGIAS_REGISTRADAS,
) -> None:
    """Registra uma nova Estratégia de amostragem no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: Identificador da estratégia exibido ao usuário no wizard.
        classe_estrategia: Classe de EstrategiaDeAmostragem associada.
        construir: Função que constrói uma instância da estratégia,
            perguntando interativamente os parâmetros que ela precisa.
        registro: Dicionário onde a estratégia é registrada. Usa
            ESTRATEGIAS_REGISTRADAS por padrão.
    """
    registrar_ou_falhar(
        nome,
        "Estratégia",
        EstrategiaRegistrada(classe_estrategia=classe_estrategia, construir=construir),
        registro,
        feminino=True,
    )


def _construir_percentual_de_linhas() -> EstrategiaDeAmostragem:
    """Pergunta o percentual de amostragem e monta o PercentualDeLinhas."""
    percentual = float(
        prompts.texto("Percentual de amostragem (0-100]:", default="10")
    )
    return PercentualDeLinhas(percentual=percentual)


registrar_estrategia(
    "Percentual de linhas", PercentualDeLinhas, _construir_percentual_de_linhas
)

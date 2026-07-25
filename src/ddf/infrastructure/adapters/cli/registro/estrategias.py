"""Registro de Estratégias de amostragem disponíveis para o wizard da CLI."""

from collections.abc import Callable
from dataclasses import dataclass

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.extractors.full_scan import FullScan
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


@dataclass(frozen=True)
class EstrategiaRegistrada:
    """Uma EstrategiaDeAmostragem registrada, junto da função que a constrói."""

    construir: Callable[[], EstrategiaDeAmostragem]


ESTRATEGIAS_REGISTRADAS: dict[str, EstrategiaRegistrada] = {}


def registrar_estrategia(
    nome: str,
    construir: Callable[[], EstrategiaDeAmostragem],
    registro: dict[str, EstrategiaRegistrada] = ESTRATEGIAS_REGISTRADAS,
) -> None:
    """Registra uma nova Estratégia de amostragem no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: Identificador da estratégia exibido ao usuário no wizard.
        construir: Função que constrói uma instância da estratégia,
            perguntando interativamente os parâmetros que ela precisa.
        registro: Dicionário onde a estratégia é registrada. Usa
            ESTRATEGIAS_REGISTRADAS por padrão.
    """
    registrar_ou_falhar(
        nome,
        "Estratégia",
        EstrategiaRegistrada(construir=construir),
        registro,
        feminino=True,
    )


def _construir_percentual_de_linhas() -> EstrategiaDeAmostragem:
    """Pergunta percentual e seed opcional, monta o PercentualDeLinhas."""
    percentual = float(
        prompts.texto("Percentual de amostragem (0-100]:", default="10")
    )
    seed_texto = prompts.texto(
        "Seed para reprodutibilidade (opcional, deixe em branco para aleatório):",
        default="",
    )
    seed = int(seed_texto) if seed_texto else None
    return PercentualDeLinhas(percentual=percentual, seed=seed)


def _construir_full_scan() -> EstrategiaDeAmostragem:
    """Constrói FullScan — sem parâmetro nenhum a perguntar."""
    return FullScan()


registrar_estrategia("Percentual de linhas", _construir_percentual_de_linhas)
registrar_estrategia("Tabela inteira (full scan)", _construir_full_scan)

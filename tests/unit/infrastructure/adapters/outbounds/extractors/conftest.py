"""Fixtures compartilhadas dos testes de adapters de Extrator."""

import pytest

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemIntegral
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)


@pytest.fixture
def percentual_de_linhas() -> PercentualDeLinhas:
    """Retorna um PercentualDeLinhas com percentual padrão de 10%."""
    return PercentualDeLinhas(percentual=10.0)


class _EstrategiaIntegralFake:
    """EstrategiaDeAmostragem fake que pede AmostragemIntegral.

    Usada só nos testes de Extrator (dispatch exaustivo) — a TabelaInteira
    pública, registrada no wizard, é implementada e testada à parte.
    """

    @property
    def nome(self) -> str:
        """Retorna o identificador fixo 'fake_integral'."""
        return "fake_integral"

    @property
    def requisicao(self) -> AmostragemIntegral:
        """Retorna AmostragemIntegral() — sem parâmetros."""
        return AmostragemIntegral()


@pytest.fixture
def estrategia_integral() -> _EstrategiaIntegralFake:
    """Retorna uma EstrategiaDeAmostragem fake que pede AmostragemIntegral."""
    return _EstrategiaIntegralFake()

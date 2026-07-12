"""Fixtures compartilhadas dos testes de adapters de Extrator."""

import pytest

from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


@pytest.fixture
def percentual_de_linhas() -> PercentualDeLinhas:
    """Retorna um PercentualDeLinhas com percentual padrão de 10%."""
    return PercentualDeLinhas(percentual=10.0)

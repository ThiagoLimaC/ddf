"""Fixtures compartilhadas dos testes de ExtratorMariaDB."""

from unittest.mock import MagicMock

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao com PercentualDeLinhas(10%)."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=10.0))


@pytest.fixture
def configuracao_integral(
    estrategia_integral: EstrategiaDeAmostragem,
) -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao que pede AmostragemIntegral (full scan)."""
    return ConfiguracaoDeExtracao(estrategia=estrategia_integral)


@pytest.fixture
def pool_classe_fake(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Substitui PooledDB por um mock, retorna a classe mockada."""
    classe_fake = MagicMock()
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb.PooledDB",
        classe_fake,
    )
    return classe_fake

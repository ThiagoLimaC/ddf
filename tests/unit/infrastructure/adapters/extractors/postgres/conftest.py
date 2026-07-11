"""Fixtures compartilhadas dos testes de ExtratorPostgres."""

from unittest.mock import MagicMock

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao com PercentualDeLinhas(10%)."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=10.0))


@pytest.fixture
def pool_classe_fake(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Substitui ThreadedConnectionPool por um mock, retorna a classe mockada."""
    classe_fake = MagicMock()
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.extractors.postgres.extrator_postgres."
        "ThreadedConnectionPool",
        classe_fake,
    )
    return classe_fake

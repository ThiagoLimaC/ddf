"""Fixtures compartilhadas dos testes de ExtratorPostgres."""

from unittest.mock import MagicMock

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.amostragem_por_faixa import (
    AmostragemPorFaixa,
)
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
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
    """Retorna uma ConfiguracaoDeExtracao que pede AmostragemIntegral."""
    return ConfiguracaoDeExtracao(estrategia=estrategia_integral)


@pytest.fixture
def configuracao_por_faixa() -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao com AmostragemPorFaixa(10%)."""
    return ConfiguracaoDeExtracao(estrategia=AmostragemPorFaixa(percentual=10.0))


@pytest.fixture
def pool_classe_fake(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Substitui ThreadedConnectionPool por um mock, retorna a classe mockada."""
    classe_fake = MagicMock()
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.outbounds.extractors.postgres._conexoes."
        "ThreadedConnectionPool",
        classe_fake,
    )
    return classe_fake

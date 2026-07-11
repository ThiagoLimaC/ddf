"""Fixtures compartilhadas para testes de domain/model (extraction, curation)."""

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


@pytest.fixture
def tipo_integer() -> TipoDeDado:
    """Retorna um TipoDeDado INTEGER simples."""
    return TipoDeDado(categoria=CategoriaDeDado.INTEGER)


@pytest.fixture
def metadados_de_amostra() -> MetadadosDeAmostra:
    """Retorna um MetadadosDeAmostra de exemplo (percentual_de_linhas)."""
    return MetadadosDeAmostra(estrategia="percentual_de_linhas", tamanho_amostra=2)


@pytest.fixture
def amostra_df() -> pl.DataFrame:
    """Retorna um pl.DataFrame mínimo para popular o campo amostra."""
    return pl.DataFrame({"id": [1, 2]})

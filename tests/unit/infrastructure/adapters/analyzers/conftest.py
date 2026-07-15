"""Fixtures compartilhadas dos testes de Analisadores."""

from collections.abc import Callable

import pytest

from ddf.domain.model.analysis import ContextoDeAnalise, iniciar_contexto
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import BancoCurado, TabelaCurada


@pytest.fixture
def tipo_varchar() -> TipoDeDado:
    """Retorna um TipoDeDado VARCHAR simples."""
    return TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=255)


@pytest.fixture
def tipo_integer() -> TipoDeDado:
    """Retorna um TipoDeDado INTEGER simples."""
    return TipoDeDado(categoria=CategoriaDeDado.INTEGER)


@pytest.fixture
def tipo_float() -> TipoDeDado:
    """Retorna um TipoDeDado FLOAT simples."""
    return TipoDeDado(categoria=CategoriaDeDado.FLOAT)


@pytest.fixture
def construir_contexto() -> Callable[[list[TabelaCurada]], ContextoDeAnalise]:
    """Retorna uma factory que monta um ContextoDeAnalise a partir de TabelaCurada."""

    def _construir(tabelas: list[TabelaCurada]) -> ContextoDeAnalise:
        return iniciar_contexto(BancoCurado(tabelas=tabelas))

    return _construir

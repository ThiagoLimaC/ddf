"""Fixtures compartilhadas para testes de domain/model/common."""

import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.requisicao_de_amostragem import AmostragemProbabilistica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


@pytest.fixture
def tipo_varchar() -> TipoDeDado:
    """Retorna um TipoDeDado VARCHAR com tamanho_maximo definido."""
    return TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=255)


@pytest.fixture
def metadados_de_amostra() -> MetadadosDeAmostra:
    """Retorna um MetadadosDeAmostra de exemplo (percentual_de_linhas)."""
    return MetadadosDeAmostra(estrategia="percentual_de_linhas", tamanho_amostra=10_000)


class EstrategiaFake:
    """EstrategiaDeAmostragem fake para testes, sem depender de PercentualDeLinhas."""

    @property
    def nome(self) -> str:
        """Retorna o identificador fixo 'fake'."""
        return "fake"

    @property
    def requisicao(self) -> AmostragemProbabilistica:
        """Retorna uma AmostragemProbabilistica fixa de 1%."""
        return AmostragemProbabilistica(percentual=1.0)


@pytest.fixture
def estrategia_fake() -> EstrategiaFake:
    """Retorna uma EstrategiaDeAmostragem fake que satisfaz o Protocol."""
    return EstrategiaFake()

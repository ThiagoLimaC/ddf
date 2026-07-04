"""Fixtures compartilhadas para testes de domain/model/common."""

import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


@pytest.fixture
def tipo_varchar() -> TipoDeDado:
    """Retorna um TipoDeDado VARCHAR com tamanho_maximo definido."""
    return TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=255)


@pytest.fixture
def metadados_de_amostra() -> MetadadosDeAmostra:
    """Retorna um MetadadosDeAmostra de exemplo (random_limit)."""
    return MetadadosDeAmostra(
        estrategia="random_limit", tamanho_amostra=10_000, total_linhas=50_000
    )


class EstrategiaFake:
    """EstrategiaDeAmostragem fake para testes, sem depender de LimiteAleatorio."""

    @property
    def nome(self) -> str:
        """Retorna o identificador fixo 'fake'."""
        return "fake"

    def consulta(self, schema: str, tabela: str) -> str:
        """Retorna uma consulta fixa, ignorando schema e tabela."""
        return f"SELECT * FROM {schema}.{tabela} LIMIT 1"


@pytest.fixture
def estrategia_fake() -> EstrategiaFake:
    """Retorna uma EstrategiaDeAmostragem fake que satisfaz o Protocol."""
    return EstrategiaFake()

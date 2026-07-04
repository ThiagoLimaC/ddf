"""Testes de MetadadosDeAmostra."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra


def test_cria_metadados_com_estrategia_e_tamanhos(
    metadados_de_amostra: MetadadosDeAmostra,
) -> None:
    """Caminho feliz: MetadadosDeAmostra guarda estrategia e os dois tamanhos."""
    assert metadados_de_amostra.estrategia == "random_limit"
    assert metadados_de_amostra.tamanho_amostra == 10_000
    assert metadados_de_amostra.total_linhas == 50_000


def test_metadados_de_amostra_e_imutavel(
    metadados_de_amostra: MetadadosDeAmostra,
) -> None:
    """Borda: MetadadosDeAmostra é imutável após construção (frozen=True)."""
    with pytest.raises(ValidationError):
        metadados_de_amostra.tamanho_amostra = 20_000

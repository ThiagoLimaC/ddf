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

def test_tamanho_amostra_negativo_levanta_validation_error() -> None:
    """Erro esperado: tamanho_amostra negativo é logicamente impossível."""
    with pytest.raises(ValidationError, match="tamanho_amostra"):
        MetadadosDeAmostra(
            estrategia="random_limit", tamanho_amostra=-1, total_linhas=10
        )


def test_total_linhas_negativo_levanta_validation_error() -> None:
    """Erro esperado: total_linhas negativo é logicamente impossível."""
    with pytest.raises(ValidationError, match="total_linhas"):
        MetadadosDeAmostra(
            estrategia="random_limit", tamanho_amostra=10, total_linhas=-1
        )

def test_metadados_de_amostra_e_imutavel(
    metadados_de_amostra: MetadadosDeAmostra,
) -> None:
    """Borda: MetadadosDeAmostra é imutável após construção (frozen=True)."""
    with pytest.raises(ValidationError):
        metadados_de_amostra.tamanho_amostra = 20_000


def test_tamanho_amostra_e_total_linhas_zero_sao_aceitos() -> None:
    """Borda: tabela vazia (0 linhas) é um estado real e válido."""
    metadados = MetadadosDeAmostra(
        estrategia="random_limit", tamanho_amostra=0, total_linhas=0
    )

    assert metadados.tamanho_amostra == 0
    assert metadados.total_linhas == 0

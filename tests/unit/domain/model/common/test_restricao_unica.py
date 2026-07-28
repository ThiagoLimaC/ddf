"""Testes de RestricaoUnica."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.restricao_unica import RestricaoUnica

# Caminho feliz


def test_restricao_unica_guarda_colunas_em_ordem() -> None:
    """Caminho feliz: RestricaoUnica guarda as colunas na ordem informada."""
    restricao = RestricaoUnica(colunas=("codigo_pais", "codigo_local"))

    assert restricao.colunas == ("codigo_pais", "codigo_local")


def test_restricao_unica_aceita_mais_de_duas_colunas() -> None:
    """Caminho feliz: RestricaoUnica não limita o número de colunas a 2."""
    restricao = RestricaoUnica(colunas=("a", "b", "c"))

    assert restricao.colunas == ("a", "b", "c")


# Erro esperado


def test_restricao_unica_com_uma_coluna_levanta_validation_error() -> None:
    """Erro esperado: 1 coluna não é composta — pertence ao campo `unica`."""
    with pytest.raises(ValidationError, match="mínimo 2 colunas"):
        RestricaoUnica(colunas=("id",))


def test_restricao_unica_sem_coluna_levanta_validation_error() -> None:
    """Erro esperado: lista vazia não representa nenhuma constraint real."""
    with pytest.raises(ValidationError, match="mínimo 2 colunas"):
        RestricaoUnica(colunas=())


def test_restricao_unica_com_coluna_duplicada_levanta_validation_error() -> None:
    """Erro esperado: mesma coluna repetida não é uma constraint válida."""
    with pytest.raises(ValidationError, match="duplicadas"):
        RestricaoUnica(colunas=("codigo", "codigo"))


# Borda


def test_restricao_unica_e_imutavel() -> None:
    """Borda: RestricaoUnica é imutável após construção (frozen=True)."""
    restricao = RestricaoUnica(colunas=("a", "b"))

    with pytest.raises(ValidationError):
        restricao.colunas = ("a", "c")  # type: ignore[misc]

"""Testes de Aviso."""

import dataclasses

import pytest

from ddf.domain.shared.aviso import Aviso


def test_cria_aviso_com_mensagem_e_origem(aviso: Aviso) -> None:
    """Caminho feliz: Aviso guarda mensagem e origem como fornecidos."""
    assert aviso.mensagem == "amostra pequena"
    assert aviso.origem == "AnalisadorDeMetricasDeColuna"


def test_aviso_e_imutavel(aviso: Aviso) -> None:
    """Erro esperado: tentar mutar um Aviso levanta FrozenInstanceError."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        aviso.mensagem = "outra mensagem"  # type: ignore[misc]

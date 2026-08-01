"""Testes de Aviso."""

import dataclasses

import pytest

from ddf.domain.shared.aviso import Aviso


class TestFeliz:
    """Caminho feliz."""

    def test_cria_aviso_com_mensagem_e_origem(self, aviso: Aviso) -> None:
        """Aviso guarda mensagem e origem como fornecidos."""
        assert aviso.mensagem == "amostra pequena"
        assert aviso.origem == "AnalisadorDeMetricasDeColuna"


class TestErro:
    """Erro esperado."""

    def test_aviso_e_imutavel(self, aviso: Aviso) -> None:
        """Tentar mutar um Aviso levanta FrozenInstanceError."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            aviso.mensagem = "outra mensagem"  # type: ignore[misc]

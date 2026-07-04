"""Fixtures compartilhadas para testes de domain/shared."""

import pytest

from ddf.domain.shared.aviso import Aviso


@pytest.fixture
def aviso() -> Aviso:
    """Retorna um Aviso de exemplo."""
    return Aviso(mensagem="amostra pequena", origem="AnalisadorDeMetricasDeColuna")

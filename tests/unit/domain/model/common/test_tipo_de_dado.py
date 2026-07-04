"""Testes de TipoDeDado."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


def test_cria_tipo_numeric_com_precisao_e_escala() -> None:
    """Caminho feliz: TipoDeDado NUMERIC guarda precisao e escala."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10, escala=2)

    assert tipo.categoria == CategoriaDeDado.NUMERIC
    assert tipo.precisao == 10
    assert tipo.escala == 2


def test_categoria_invalida_levanta_validation_error() -> None:
    """Erro esperado: categoria fora do Enum levanta ValidationError."""
    with pytest.raises(ValidationError):
        TipoDeDado(categoria="POSTGRES_ARRAY")  # type: ignore[arg-type]


def test_categoria_unknown_nao_levanta_excecao() -> None:
    """Borda: UNKNOWN é aceito sem atributos extras, sem exceção por tipo raro."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.UNKNOWN)

    assert tipo.categoria == CategoriaDeDado.UNKNOWN
    assert tipo.precisao is None
    assert tipo.escala is None
    assert tipo.tamanho_maximo is None


def test_tipo_de_dado_e_imutavel(tipo_varchar: TipoDeDado) -> None:
    """Borda: TipoDeDado é imutável após construção (frozen=True via ConfigDict)."""
    with pytest.raises(ValidationError):
        tipo_varchar.tamanho_maximo = 500

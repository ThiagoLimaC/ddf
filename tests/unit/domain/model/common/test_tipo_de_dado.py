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


def test_integer_com_tamanho_maximo_levanta_validation_error() -> None:
    """Erro esperado: atributo de outra categoria (tamanho_maximo) em INTEGER."""
    with pytest.raises(ValidationError, match="INTEGER"):
        TipoDeDado(categoria=CategoriaDeDado.INTEGER, tamanho_maximo=10)


def test_varchar_com_precisao_levanta_validation_error() -> None:
    """Erro esperado: atributo de NUMERIC (precisao) usado em VARCHAR."""
    with pytest.raises(ValidationError, match="VARCHAR"):
        TipoDeDado(categoria=CategoriaDeDado.VARCHAR, precisao=10)


def test_numeric_com_tamanho_maximo_levanta_validation_error() -> None:
    """Erro esperado: atributo de VARCHAR (tamanho_maximo) usado em NUMERIC."""
    with pytest.raises(ValidationError, match="NUMERIC"):
        TipoDeDado(categoria=CategoriaDeDado.NUMERIC, tamanho_maximo=10)


def test_numeric_apenas_com_precisao_e_aceito() -> None:
    """Borda: NUMERIC aceita só precisao preenchida, sem escala."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10)

    assert tipo.precisao == 10
    assert tipo.escala is None


def test_numeric_com_escala_sem_precisao_levanta_validation_error() -> None:
    """Erro esperado: escala sem precisao é um NUMERIC inconsistente."""
    with pytest.raises(ValidationError, match="escala"):
        TipoDeDado(categoria=CategoriaDeDado.NUMERIC, escala=2)

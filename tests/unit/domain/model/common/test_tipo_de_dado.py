"""Testes de TipoDeDado."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado

# Caminho feliz


def test_cria_tipo_numeric_com_precisao_e_escala() -> None:
    """Caminho feliz: TipoDeDado NUMERIC guarda precisao e escala."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10, escala=2)

    assert tipo.categoria == CategoriaDeDado.NUMERIC
    assert tipo.precisao == 10
    assert tipo.escala == 2


def test_cria_tipo_float_com_precisao_dupla() -> None:
    """Caminho feliz: FLOAT distingue real/double precision via com_precisao_dupla."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=True)

    assert tipo.categoria == CategoriaDeDado.FLOAT
    assert tipo.com_precisao_dupla is True
    assert tipo.precisao is None
    assert tipo.escala is None


def test_cria_tipo_char_com_tamanho_fixo() -> None:
    """Caminho feliz: CHAR guarda tamanho_fixo, distinto de tamanho_maximo."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_fixo=10)

    assert tipo.categoria == CategoriaDeDado.CHAR
    assert tipo.tamanho_fixo == 10


def test_cria_tipo_uuid_sem_atributos() -> None:
    """Caminho feliz: UUID não aceita nenhum atributo extra."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.UUID)

    assert tipo.categoria == CategoriaDeDado.UUID


def test_cria_tipo_timestamp_com_timezone() -> None:
    """Caminho feliz: TIMESTAMP e TIME compartilham o atributo com_timezone."""
    com_tz = TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=True)
    sem_tz = TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=False)

    assert com_tz.com_timezone is True
    assert sem_tz.com_timezone is False


# Erro esperado


def test_categoria_invalida_levanta_validation_error() -> None:
    """Erro esperado: categoria fora do Enum levanta ValidationError."""
    with pytest.raises(ValidationError):
        TipoDeDado(categoria="POSTGRES_ARRAY")  # type: ignore[arg-type]


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


def test_numeric_com_escala_sem_precisao_levanta_validation_error() -> None:
    """Erro esperado: escala sem precisao é um NUMERIC inconsistente."""
    with pytest.raises(ValidationError, match="escala"):
        TipoDeDado(categoria=CategoriaDeDado.NUMERIC, escala=2)


def test_float_com_precisao_levanta_validation_error() -> None:
    """Erro esperado: FLOAT não aceita precisao (não é decimal configurável)."""
    with pytest.raises(ValidationError, match="FLOAT"):
        TipoDeDado(categoria=CategoriaDeDado.FLOAT, precisao=24)


def test_char_com_tamanho_maximo_levanta_validation_error() -> None:
    """Erro esperado: CHAR não aceita tamanho_maximo (atributo é de VARCHAR)."""
    with pytest.raises(ValidationError, match="CHAR"):
        TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_maximo=10)


def test_uuid_com_tamanho_fixo_levanta_validation_error() -> None:
    """Erro esperado: UUID não aceita tamanho_fixo."""
    with pytest.raises(ValidationError, match="UUID"):
        TipoDeDado(categoria=CategoriaDeDado.UUID, tamanho_fixo=36)


def test_date_com_timezone_levanta_validation_error() -> None:
    """Erro esperado: com_timezone é exclusivo de TIMESTAMP/TIME, não de DATE."""
    with pytest.raises(ValidationError, match="DATE"):
        TipoDeDado(categoria=CategoriaDeDado.DATE, com_timezone=True)


def test_numeric_com_precisao_dupla_levanta_validation_error() -> None:
    """Erro esperado: com_precisao_dupla é exclusivo de FLOAT, não de NUMERIC."""
    with pytest.raises(ValidationError, match="NUMERIC"):
        TipoDeDado(categoria=CategoriaDeDado.NUMERIC, com_precisao_dupla=True)


# Borda


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


def test_numeric_apenas_com_precisao_e_aceito() -> None:
    """Borda: NUMERIC aceita só precisao preenchida, sem escala."""
    tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10)

    assert tipo.precisao == 10
    assert tipo.escala is None

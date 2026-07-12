"""Testes de mapear_tipo_postgres."""

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)

# Caminho feliz


def test_mapeia_character_varying_para_varchar() -> None:
    """Caminho feliz: character varying(n) vira VARCHAR com tamanho_maximo."""
    tipo = mapear_tipo_postgres("character varying", tamanho_maximo=255)

    assert tipo.categoria == CategoriaDeDado.VARCHAR
    assert tipo.tamanho_maximo == 255


def test_mapeia_character_para_char() -> None:
    """Caminho feliz: character(n) vira CHAR com tamanho_fixo."""
    tipo = mapear_tipo_postgres("character", tamanho_maximo=10)

    assert tipo.categoria == CategoriaDeDado.CHAR
    assert tipo.tamanho_fixo == 10


def test_mapeia_text_para_text() -> None:
    """Caminho feliz: text vira TEXT sem atributos."""
    assert mapear_tipo_postgres("text").categoria == CategoriaDeDado.TEXT


def test_mapeia_numeric_para_numeric_com_precisao_e_escala() -> None:
    """Caminho feliz: numeric(p,s) vira NUMERIC com precisao e escala."""
    tipo = mapear_tipo_postgres("numeric", precisao=10, escala=2)

    assert tipo.categoria == CategoriaDeDado.NUMERIC
    assert tipo.precisao == 10
    assert tipo.escala == 2


def test_mapeia_smallint_e_integer_para_integer() -> None:
    """Caminho feliz: smallint e integer compartilham a categoria INTEGER."""
    assert mapear_tipo_postgres("smallint").categoria == CategoriaDeDado.INTEGER
    assert mapear_tipo_postgres("integer").categoria == CategoriaDeDado.INTEGER


def test_mapeia_bigint_para_bigint() -> None:
    """Caminho feliz: bigint vira BIGINT."""
    assert mapear_tipo_postgres("bigint").categoria == CategoriaDeDado.BIGINT


def test_mapeia_real_e_double_precision_com_precisao_dupla() -> None:
    """Caminho feliz: real/double precision compartilham FLOAT, variam em largura."""
    real = mapear_tipo_postgres("real")
    double = mapear_tipo_postgres("double precision")

    assert real.categoria == CategoriaDeDado.FLOAT
    assert real.com_precisao_dupla is False
    assert double.categoria == CategoriaDeDado.FLOAT
    assert double.com_precisao_dupla is True


def test_mapeia_boolean_para_boolean() -> None:
    """Caminho feliz: boolean vira BOOLEAN."""
    assert mapear_tipo_postgres("boolean").categoria == CategoriaDeDado.BOOLEAN


def test_mapeia_timestamp_com_e_sem_timezone() -> None:
    """Caminho feliz: timestamp with/without time zone vira TIMESTAMP com_timezone."""
    sem_tz = mapear_tipo_postgres("timestamp without time zone")
    com_tz = mapear_tipo_postgres("timestamp with time zone")

    assert sem_tz.categoria == CategoriaDeDado.TIMESTAMP
    assert sem_tz.com_timezone is False
    assert com_tz.categoria == CategoriaDeDado.TIMESTAMP
    assert com_tz.com_timezone is True


def test_mapeia_time_com_e_sem_timezone() -> None:
    """Caminho feliz: time with/without time zone vira TIME com_timezone."""
    sem_tz = mapear_tipo_postgres("time without time zone")
    com_tz = mapear_tipo_postgres("time with time zone")

    assert sem_tz.categoria == CategoriaDeDado.TIME
    assert sem_tz.com_timezone is False
    assert com_tz.categoria == CategoriaDeDado.TIME
    assert com_tz.com_timezone is True


def test_mapeia_date_para_date() -> None:
    """Caminho feliz: date vira DATE."""
    assert mapear_tipo_postgres("date").categoria == CategoriaDeDado.DATE


def test_mapeia_json_e_jsonb_para_json() -> None:
    """Caminho feliz: json e jsonb compartilham a categoria JSON."""
    assert mapear_tipo_postgres("json").categoria == CategoriaDeDado.JSON
    assert mapear_tipo_postgres("jsonb").categoria == CategoriaDeDado.JSON


def test_mapeia_uuid_para_uuid() -> None:
    """Caminho feliz: uuid vira UUID."""
    assert mapear_tipo_postgres("uuid").categoria == CategoriaDeDado.UUID


# Borda


def test_tipo_desconhecido_vira_unknown() -> None:
    """Borda: tipo fora da tabela de mapeamento vira UNKNOWN, sem exceção."""
    assert mapear_tipo_postgres("bytea").categoria == CategoriaDeDado.UNKNOWN
    assert mapear_tipo_postgres("ARRAY").categoria == CategoriaDeDado.UNKNOWN

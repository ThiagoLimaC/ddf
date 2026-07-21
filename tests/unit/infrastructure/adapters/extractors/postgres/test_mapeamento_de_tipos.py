"""Testes de mapear_tipo_postgres."""

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)

# Caminho feliz


def test_mapeia_varchar_para_varchar() -> None:
    """Caminho feliz: udt_name varchar vira VARCHAR com tamanho_maximo."""
    tipo = mapear_tipo_postgres("varchar", tamanho_maximo=255)

    assert tipo.categoria == CategoriaDeDado.VARCHAR
    assert tipo.tamanho_maximo == 255


def test_mapeia_bpchar_para_char() -> None:
    """Caminho feliz: udt_name bpchar (character(n)) vira CHAR com tamanho_fixo."""
    tipo = mapear_tipo_postgres("bpchar", tamanho_maximo=10)

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


def test_mapeia_int2_e_int4_para_integer() -> None:
    """Caminho feliz: udt_name int2 (smallint) e int4 (integer) viram INTEGER."""
    assert mapear_tipo_postgres("int2").categoria == CategoriaDeDado.INTEGER
    assert mapear_tipo_postgres("int4").categoria == CategoriaDeDado.INTEGER


def test_mapeia_int8_para_bigint() -> None:
    """Caminho feliz: udt_name int8 (bigint) vira BIGINT."""
    assert mapear_tipo_postgres("int8").categoria == CategoriaDeDado.BIGINT


def test_mapeia_float4_e_float8_com_precisao_dupla() -> None:
    """Caminho feliz: float4/float8 (real/double precision) compartilham FLOAT."""
    real = mapear_tipo_postgres("float4")
    double = mapear_tipo_postgres("float8")

    assert real.categoria == CategoriaDeDado.FLOAT
    assert real.com_precisao_dupla is False
    assert double.categoria == CategoriaDeDado.FLOAT
    assert double.com_precisao_dupla is True


def test_mapeia_bool_para_boolean() -> None:
    """Caminho feliz: udt_name bool vira BOOLEAN."""
    assert mapear_tipo_postgres("bool").categoria == CategoriaDeDado.BOOLEAN


def test_mapeia_timestamp_com_e_sem_timezone() -> None:
    """Caminho feliz: udt_name timestamp/timestamptz vira TIMESTAMP com_timezone."""
    sem_tz = mapear_tipo_postgres("timestamp")
    com_tz = mapear_tipo_postgres("timestamptz")

    assert sem_tz.categoria == CategoriaDeDado.TIMESTAMP
    assert sem_tz.com_timezone is False
    assert com_tz.categoria == CategoriaDeDado.TIMESTAMP
    assert com_tz.com_timezone is True


def test_mapeia_time_com_e_sem_timezone() -> None:
    """Caminho feliz: udt_name time/timetz vira TIME com_timezone."""
    sem_tz = mapear_tipo_postgres("time")
    com_tz = mapear_tipo_postgres("timetz")

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


def test_mapeia_array_com_elemento_reconhecido() -> None:
    """Caminho feliz: udt_name com prefixo "_" vira ARRAY, elemento sem o "_"."""
    inteiros = mapear_tipo_postgres("_int4")
    textos = mapear_tipo_postgres("_varchar")

    assert inteiros.categoria == CategoriaDeDado.ARRAY
    assert inteiros.elemento == CategoriaDeDado.INTEGER
    assert textos.categoria == CategoriaDeDado.ARRAY
    assert textos.elemento == CategoriaDeDado.VARCHAR


# Borda


def test_tipo_desconhecido_vira_unknown() -> None:
    """Borda: udt_name fora da tabela de mapeamento vira UNKNOWN, sem exceção."""
    assert mapear_tipo_postgres("bytea").categoria == CategoriaDeDado.UNKNOWN


def test_array_com_udt_name_desconhecido_fica_sem_elemento() -> None:
    """Borda: ARRAY de um tipo sem entrada em _CATEGORIAS_SIMPLES não quebra."""
    tipo = mapear_tipo_postgres("_ponto_geografico")

    assert tipo.categoria == CategoriaDeDado.ARRAY
    assert tipo.elemento is None

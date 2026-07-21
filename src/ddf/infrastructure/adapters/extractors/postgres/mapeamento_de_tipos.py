"""Mapeamento de tipos de coluna do Postgres para TipoDeDado."""

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado

# Chaveado por udt_name (pg_type.typname via information_schema.columns.
# udt_name) — não por data_type.

_CATEGORIAS_SIMPLES: dict[str, CategoriaDeDado] = {
    "text": CategoriaDeDado.TEXT,
    "varchar": CategoriaDeDado.VARCHAR,
    "bpchar": CategoriaDeDado.CHAR,
    "numeric": CategoriaDeDado.NUMERIC,
    "int2": CategoriaDeDado.INTEGER,
    "int4": CategoriaDeDado.INTEGER,
    "int8": CategoriaDeDado.BIGINT,
    "bool": CategoriaDeDado.BOOLEAN,
    "date": CategoriaDeDado.DATE,
    "json": CategoriaDeDado.JSON,
    "jsonb": CategoriaDeDado.JSON,
    "uuid": CategoriaDeDado.UUID,
    "float4": CategoriaDeDado.FLOAT,
    "float8": CategoriaDeDado.FLOAT,
    "timestamp": CategoriaDeDado.TIMESTAMP,
    "timestamptz": CategoriaDeDado.TIMESTAMP,
    "time": CategoriaDeDado.TIME,
    "timetz": CategoriaDeDado.TIME,
}


def mapear_tipo_postgres(
    udt_name: str,
    tamanho_maximo: int | None = None,
    precisao: int | None = None,
    escala: int | None = None,
) -> TipoDeDado:
    """Mapeia um tipo de coluna do Postgres para TipoDeDado.

    Tipos fora da tabela de mapeamento caem em CategoriaDeDado.UNKNOWN, nunca
    levantam exceção. Um udt_name com o prefixo "_" (ex. "_int4") identifica
    uma coluna ARRAY 

    Args:
        udt_name: information_schema.columns.udt_name — nome interno do
            catálogo do Postgres (pg_type.typname), uma palavra só por tipo.
        tamanho_maximo: character_maximum_length, usado por VARCHAR/CHAR.
        precisao: numeric_precision, usado por NUMERIC.
        escala: numeric_scale, usado por NUMERIC.

    Returns:
        TipoDeDado mapeado. Para udt_name com prefixo "_", categoria é
        sempre CategoriaDeDado.ARRAY; elemento é a categoria do tipo sem o
        prefixo, ou None se não reconhecido (array continua identificável,
        só sem o elemento) — nunca com atributo de precisão, por decisão de
        escopo (ver TipoDeDado.elemento).
    """
    if udt_name.startswith("_"):
        elemento = _CATEGORIAS_SIMPLES.get(udt_name.removeprefix("_"))
        return TipoDeDado(categoria=CategoriaDeDado.ARRAY, elemento=elemento)
    if udt_name == "varchar":
        return TipoDeDado(
            categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=tamanho_maximo
        )
    if udt_name == "bpchar":
        return TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_fixo=tamanho_maximo)
    if udt_name == "numeric":
        return TipoDeDado(
            categoria=CategoriaDeDado.NUMERIC, precisao=precisao, escala=escala
        )
    if udt_name == "timestamp":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=False)
    if udt_name == "timestamptz":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=True)
    if udt_name == "time":
        return TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=False)
    if udt_name == "timetz":
        return TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=True)
    if udt_name == "float4":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=False)
    if udt_name == "float8":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=True)

    categoria = _CATEGORIAS_SIMPLES.get(udt_name, CategoriaDeDado.UNKNOWN)
    return TipoDeDado(categoria=categoria)

"""Mapeamento de tipos de coluna do Postgres para TipoDeDado."""

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado

_CATEGORIAS_SIMPLES: dict[str, CategoriaDeDado] = {
    "text": CategoriaDeDado.TEXT,
    "smallint": CategoriaDeDado.INTEGER,
    "integer": CategoriaDeDado.INTEGER,
    "bigint": CategoriaDeDado.BIGINT,
    "boolean": CategoriaDeDado.BOOLEAN,
    "date": CategoriaDeDado.DATE,
    "json": CategoriaDeDado.JSON,
    "jsonb": CategoriaDeDado.JSON,
    "uuid": CategoriaDeDado.UUID,
}


def mapear_tipo_postgres(
    data_type: str,
    tamanho_maximo: int | None = None,
    precisao: int | None = None,
    escala: int | None = None,
) -> TipoDeDado:
    """Mapeia um tipo de coluna do Postgres para TipoDeDado.

    Tipos fora da tabela de mapeamento caem em CategoriaDeDado.UNKNOWN, nunca
    levantam exceção.

    Args:
        data_type: valor de information_schema.columns.data_type.
        tamanho_maximo: character_maximum_length, usado por VARCHAR/CHAR.
        precisao: numeric_precision, usado por NUMERIC.
        escala: numeric_scale, usado por NUMERIC.
    """
    if data_type == "character varying":
        return TipoDeDado(
            categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=tamanho_maximo
        )
    if data_type == "character":
        return TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_fixo=tamanho_maximo)
    if data_type == "numeric":
        return TipoDeDado(
            categoria=CategoriaDeDado.NUMERIC, precisao=precisao, escala=escala
        )
    if data_type == "timestamp without time zone":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=False)
    if data_type == "timestamp with time zone":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=True)
    if data_type == "time without time zone":
        return TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=False)
    if data_type == "time with time zone":
        return TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=True)
    if data_type == "real":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=False)
    if data_type == "double precision":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=True)

    categoria = _CATEGORIAS_SIMPLES.get(data_type, CategoriaDeDado.UNKNOWN)
    return TipoDeDado(categoria=categoria)

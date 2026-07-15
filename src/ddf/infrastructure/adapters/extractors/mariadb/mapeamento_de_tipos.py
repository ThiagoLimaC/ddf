"""Mapeamento de tipos de coluna do MariaDB para TipoDeDado."""

import re

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado

_CATEGORIAS_SIMPLES: dict[str, CategoriaDeDado] = {
    "tinytext": CategoriaDeDado.TEXT,
    "text": CategoriaDeDado.TEXT,
    "mediumtext": CategoriaDeDado.TEXT,
    "longtext": CategoriaDeDado.TEXT,
    "tinyint": CategoriaDeDado.INTEGER,
    "smallint": CategoriaDeDado.INTEGER,
    "mediumint": CategoriaDeDado.INTEGER,
    "int": CategoriaDeDado.INTEGER,
    "bigint": CategoriaDeDado.BIGINT,
    "date": CategoriaDeDado.DATE,
    "json": CategoriaDeDado.JSON,
    "uuid": CategoriaDeDado.UUID,
    "time": CategoriaDeDado.TIME,
}

_PADRAO_VALOR_ENUM = re.compile(r"'((?:[^']|'')*)'")


def _extrair_valores_enum(column_type: str) -> tuple[str, ...]:
    """Extrai os valores literais de um COLUMN_TYPE enum(...)/set(...).

    Args:
        column_type: valor de information_schema.columns.COLUMN_TYPE, ex.
            "enum('ativo','inativo')" — aspas simples duplicadas (`''`)
            escapam uma aspa literal dentro de um valor.
    """
    valores = []
    for bruto in _PADRAO_VALOR_ENUM.findall(column_type):
        valores.append(bruto.replace("''", "'"))
    return tuple(valores)


def mapear_tipo_mariadb(
    data_type: str,
    column_type: str,
    tamanho_maximo: int | None = None,
    precisao: int | None = None,
    escala: int | None = None,
) -> TipoDeDado:
    """Mapeia um tipo de coluna do MariaDB para TipoDeDado.

    Tipos fora da tabela de mapeamento caem em CategoriaDeDado.UNKNOWN, nunca
    levantam exceção. `tinyint` sempre vira INTEGER aqui, mesmo `tinyint(1)`
    — a promoção pra BOOLEAN é responsabilidade de ExtratorMariaDB, baseada
    na amostra real, não desta função pura de metadado.

    Args:
        data_type: valor de information_schema.columns.DATA_TYPE.
        column_type: valor de information_schema.columns.COLUMN_TYPE, usado
            só para extrair os valores permitidos de enum/set.
        tamanho_maximo: character_maximum_length, usado por VARCHAR/CHAR.
        precisao: numeric_precision, usado por NUMERIC (decimal).
        escala: numeric_scale, usado por NUMERIC (decimal).
    """
    if data_type == "varchar":
        return TipoDeDado(
            categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=tamanho_maximo
        )
    if data_type == "char":
        return TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_fixo=tamanho_maximo)
    if data_type == "decimal":
        return TipoDeDado(
            categoria=CategoriaDeDado.NUMERIC, precisao=precisao, escala=escala
        )
    if data_type == "float":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=False)
    if data_type == "double":
        return TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=True)
    if data_type == "datetime":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=False)
    if data_type == "timestamp":
        return TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=True)
    if data_type == "enum":
        return TipoDeDado(
            categoria=CategoriaDeDado.ENUM,
            valores_permitidos=_extrair_valores_enum(column_type),
        )
    if data_type == "set":
        return TipoDeDado(
            categoria=CategoriaDeDado.SET,
            valores_permitidos=_extrair_valores_enum(column_type),
        )

    categoria = _CATEGORIAS_SIMPLES.get(data_type, CategoriaDeDado.UNKNOWN)
    return TipoDeDado(categoria=categoria)

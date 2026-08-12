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
    "uuid": CategoriaDeDado.UUID,
}

_PADRAO_VALOR_ENUM = re.compile(r"'((?:[^']|'')*)'")


_PADRAO_CHECK_JSON_VALID = re.compile(r"^json_valid\(`(\w+)`\)$", re.IGNORECASE)


def _extrair_coluna_json_valid(check_clause: str) -> str | None:
    """Extrai o nome da coluna de um CHECK_CLAUSE do tipo json_valid(`col`).

    MariaDB reporta `data_type = "longtext"` para colunas `JSON` — a coluna
    real vira `LONGTEXT` com um `CHECK(json_valid(...))` implícito, nunca
    reporta `"json"` como data_type. Esta função identifica esse padrão
    específico de CHECK_CLAUSE para permitir a reclassificação correta em
    `ExtratorMariaDB`.

    Args:
        check_clause: valor de information_schema.CHECK_CONSTRAINTS.
            CHECK_CLAUSE.

    Returns:
        O nome da coluna, ou None se check_clause não seguir o padrão
        json_valid(`<coluna>`) — CHECK constraints não relacionados a JSON
        (ex. "`idade` >= 0") são ignorados, não geram erro.
    """
    casamento = _PADRAO_CHECK_JSON_VALID.match(check_clause)
    return casamento.group(1) if casamento else None


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
    precisao_fracionaria: int | None = None,
) -> TipoDeDado:
    """Mapeia um tipo de coluna do MariaDB para TipoDeDado.

    Tipos fora da tabela de mapeamento caem em CategoriaDeDado.UNKNOWN, nunca
    levantam exceção. `tinyint` sempre vira INTEGER aqui, mesmo `tinyint(1)`
    — a promoção pra BOOLEAN é responsabilidade de ExtratorMariaDB, baseada
    na amostra real, não desta função pura de metadado. `TIMESTAMP` guarda o
    valor internamente em UTC e converte conforme o timezone da sessão em
    cada leitura/escrita; `DATETIME` grava o valor literal, sem conversão —
    é essa diferença de comportamento que `com_timezone` documenta, não a
    presença de um offset por linha (nenhum dos dois motores tem isso).

    Args:
        data_type: valor de information_schema.columns.DATA_TYPE.
        column_type: valor de information_schema.columns.COLUMN_TYPE, usado
            só para extrair os valores permitidos de enum/set.
        tamanho_maximo: character_maximum_length, usado por VARCHAR/CHAR.
        precisao: numeric_precision, usado por NUMERIC (decimal).
        escala: numeric_scale, usado por NUMERIC (decimal).
        precisao_fracionaria: datetime_precision, usado por
            TIMESTAMP/DATETIME/TIME (dígitos de fração de segundo, 0-6).
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
        return TipoDeDado(
            categoria=CategoriaDeDado.TIMESTAMP,
            com_timezone=False,
            precisao_fracionaria=precisao_fracionaria,
        )
    if data_type == "timestamp":
        return TipoDeDado(
            categoria=CategoriaDeDado.TIMESTAMP,
            com_timezone=True,
            precisao_fracionaria=precisao_fracionaria,
        )
    if data_type == "time":
        return TipoDeDado(
            categoria=CategoriaDeDado.TIME,
            precisao_fracionaria=precisao_fracionaria,
        )
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

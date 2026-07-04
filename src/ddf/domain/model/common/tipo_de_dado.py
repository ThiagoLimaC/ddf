"""Tipo de dado de coluna, compartilhado entre os três Bounded Contexts."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class CategoriaDeDado(str, Enum):
    """Categoria normalizada de um tipo de dado de coluna."""

    VARCHAR = "VARCHAR"
    TEXT = "TEXT"
    NUMERIC = "NUMERIC"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    DATE = "DATE"
    JSON = "JSON"
    UNKNOWN = "UNKNOWN"


class TipoDeDado(BaseModel):
    """Representa o tipo de dado de uma coluna, com atributos de precisão."""

    model_config = ConfigDict(frozen=True)

    categoria: CategoriaDeDado
    precisao: int | None = None
    escala: int | None = None
    tamanho_maximo: int | None = None

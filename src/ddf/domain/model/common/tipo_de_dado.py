"""Tipo de dado de coluna, compartilhado entre os três Bounded Contexts."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator
from typing_extensions import Self


class CategoriaDeDado(str, Enum):
    """Categoria normalizada de um tipo de dado de coluna."""

    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    TEXT = "TEXT"
    NUMERIC = "NUMERIC"
    FLOAT = "FLOAT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    TIME = "TIME"
    DATE = "DATE"
    JSON = "JSON"
    UUID = "UUID"
    ENUM = "ENUM"
    SET = "SET"
    ARRAY = "ARRAY"
    UNKNOWN = "UNKNOWN"


_ATRIBUTOS_PERMITIDOS: dict[CategoriaDeDado, set[str]] = {
    CategoriaDeDado.NUMERIC: {"precisao", "escala"},
    CategoriaDeDado.VARCHAR: {"tamanho_maximo"},
    CategoriaDeDado.CHAR: {"tamanho_fixo"},
    CategoriaDeDado.TIMESTAMP: {"com_timezone", "precisao_fracionaria"},
    CategoriaDeDado.TIME: {"com_timezone", "precisao_fracionaria"},
    CategoriaDeDado.FLOAT: {"com_precisao_dupla"},
    CategoriaDeDado.ENUM: {"valores_permitidos"},
    CategoriaDeDado.SET: {"valores_permitidos"},
    CategoriaDeDado.ARRAY: {"elemento"},
}


class TipoDeDado(BaseModel):
    """Representa o tipo de dado de uma coluna, com atributos de precisão."""

    model_config = ConfigDict(frozen=True)

    categoria: CategoriaDeDado
    precisao: int | None = None
    escala: int | None = None
    tamanho_maximo: int | None = None
    tamanho_fixo: int | None = None
    com_timezone: bool | None = None
    precisao_fracionaria: int | None = None
    com_precisao_dupla: bool | None = None
    valores_permitidos: tuple[str, ...] | None = None
    # Só a categoria do elemento (ARRAY) — sem precisão/tamanho do elemento
    elemento: CategoriaDeDado | None = None

    @model_validator(mode="after")
    def _valida_atributos_por_categoria(self) -> Self:
        """Rejeita atributos de precisão que não fazem sentido para a categoria."""
        permitidos = _ATRIBUTOS_PERMITIDOS.get(self.categoria, set())
        preenchidos = {
            campo
            for campo in (
                "precisao",
                "escala",
                "tamanho_maximo",
                "tamanho_fixo",
                "com_timezone",
                "precisao_fracionaria",
                "com_precisao_dupla",
                "valores_permitidos",
                "elemento",
            )
            if getattr(self, campo) is not None
        }
        invalidos = preenchidos - permitidos
        if invalidos:
            raise ValueError(
                f"Categoria '{self.categoria.value}' não aceita os atributos "
                f"{sorted(invalidos)}."
            )
        if self.escala is not None and self.precisao is None:
            raise ValueError("'escala' requer 'precisao' preenchida.")
        return self

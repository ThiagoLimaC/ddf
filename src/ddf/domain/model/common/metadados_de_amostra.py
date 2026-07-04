"""Metadados sobre a amostragem realizada em uma tabela."""

from pydantic import BaseModel, ConfigDict


class MetadadosDeAmostra(BaseModel):
    """Descreve como uma amostra de dados foi extraída de uma tabela."""

    model_config = ConfigDict(frozen=True)

    estrategia: str
    tamanho_amostra: int
    total_linhas: int

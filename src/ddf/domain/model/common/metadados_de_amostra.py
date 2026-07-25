"""Metadados sobre a amostragem realizada em uma tabela."""

from pydantic import BaseModel, ConfigDict, Field


class MetadadosDeAmostra(BaseModel):
    """Descreve como uma amostra de dados foi extraída de uma tabela.

    `percentual`/`seed` guardam os valores efetivamente usados na consulta
    (não os configurados) — em `AmostragemProbabilistica` sem seed, o
    Extrator gera um antes de montar a query; é esse valor gerado que
    aparece aqui, nunca `None`, para a amostra ser reproduzível a partir só
    do artefato. Ambos ficam `None` em `full_scan`, onde não há política
    probabilística nenhuma.
    """

    model_config = ConfigDict(frozen=True)

    estrategia: str
    tamanho_amostra: int = Field(ge=0)
    percentual: float | None = Field(default=None, gt=0, le=100)
    seed: int | None = None

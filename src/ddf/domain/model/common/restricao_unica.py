"""Grupo de colunas cobertas por uma mesma constraint UNIQUE composta."""

from pydantic import BaseModel, ConfigDict, model_validator
from typing_extensions import Self


class RestricaoUnica(BaseModel):
    """Grupo de 2+ colunas cobertas por uma mesma constraint UNIQUE composta.

    Compartilhada pelos três Bounded Contexts (Extraction, Curation,
    Analysis), mesmo padrão de ReferenciaDeColuna. Constraint UNIQUE de uma
    única coluna continua representada pelo campo `unica` já existente em
    ColunaExtraida/ColunaCurada/ColunaAnalisada — RestricaoUnica só existe
    para o caso composto, que `unica` não consegue expressar.
    """

    model_config = ConfigDict(frozen=True)

    colunas: tuple[str, ...]

    @model_validator(mode="after")
    def _valida_minimo_duas_colunas_sem_duplicata(self) -> Self:
        """Garante que a restrição é de fato composta e sem coluna repetida."""
        if len(self.colunas) < 2:
            raise ValueError("RestricaoUnica exige no mínimo 2 colunas.")
        if len(set(self.colunas)) != len(self.colunas):
            raise ValueError(f"Colunas duplicadas em RestricaoUnica: {self.colunas}.")
        return self

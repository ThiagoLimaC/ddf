"""Grupo de colunas cobertas por uma mesma constraint FK composta."""

from pydantic import BaseModel, ConfigDict, model_validator
from typing_extensions import Self


class RestricaoDeFkComposta(BaseModel):
    """Grupo de 2+ colunas locais que, juntas, formam uma FK composta.

    Compartilhada pelos três Bounded Contexts (Extraction, Curation,
    Analysis), mesmo padrão de RestricaoUnica. Uma FK de coluna única
    continua representada por ColunaExtraida/ColunaCurada/ColunaAnalisada
    `.referencias: list[ReferenciaDeColuna]` — RestricaoDeFkComposta só
    existe para o caso composto, que uma `ReferenciaDeColuna` por coluna
    não consegue expressar (não agrupa colunas de uma mesma constraint).
    """

    model_config = ConfigDict(frozen=True)

    colunas_locais: tuple[str, ...]
    nome_escopo_referenciado: str
    nome_tabela_referenciada: str
    colunas_referenciadas: tuple[str, ...]

    @model_validator(mode="after")
    def _valida_colunas_locais(self) -> Self:
        """Garante que a restrição é de fato composta, sem duplicata e pareada."""
        if len(self.colunas_locais) < 2:
            raise ValueError("RestricaoDeFkComposta exige no mínimo 2 colunas locais.")
        if len(set(self.colunas_locais)) != len(self.colunas_locais):
            raise ValueError(
                f"Colunas locais duplicadas em RestricaoDeFkComposta: "
                f"{self.colunas_locais}."
            )
        if len(self.colunas_referenciadas) != len(self.colunas_locais):
            raise ValueError(
                "RestricaoDeFkComposta exige o mesmo número de colunas locais e "
                f"referenciadas: {len(self.colunas_locais)} != "
                f"{len(self.colunas_referenciadas)}."
            )
        return self

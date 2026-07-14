"""Referência plenamente qualificada de uma chave estrangeira."""

from pydantic import BaseModel, ConfigDict


class ReferenciaDeColuna(BaseModel):
    """Aponta para escopo, tabela e coluna de destino de uma chave estrangeira.

    Compartilhada pelos três Bounded Contexts (Extraction, Curation,
    Analysis) — cada um usa em sua própria representação de coluna
    (ColunaExtraida, ColunaCurada, ColunaAnalisada).
    """

    model_config = ConfigDict(frozen=True)

    nome_escopo: str
    nome_tabela: str
    nome_coluna: str

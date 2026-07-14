"""Extraction Context — estrutura crua da fonte de dados, sem curadoria."""

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado


class ColunaExtraida(BaseModel):
    """Coluna de uma tabela, tal como extraída da fonte, sem curadoria."""

    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    tabela_referenciada: str | None = None
    coluna_referenciada: str | None = None

    @model_validator(mode="after")
    def _valida_referencia_de_chave_estrangeira(self) -> Self:
        """Garante que chave_estrangeira e a referência de destino andam juntas."""
        tem_referencia = (
            self.tabela_referenciada is not None
            and self.coluna_referenciada is not None
        )
        if self.chave_estrangeira and not tem_referencia:
            raise ValueError(
                "chave_estrangeira=True exige tabela_referenciada e "
                "coluna_referenciada preenchidos."
            )
        if not self.chave_estrangeira and (
            self.tabela_referenciada is not None
            or self.coluna_referenciada is not None
        ):
            raise ValueError(
                "tabela_referenciada/coluna_referenciada só fazem sentido com "
                "chave_estrangeira=True."
            )
        return self


class TabelaExtraida(BaseModel):
    """Tabela extraída da fonte, com estrutura, amostra e metadados."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaExtraida]
    total_linhas: int = Field(ge=0)
    amostra: pl.DataFrame
    metadados_amostra: MetadadosDeAmostra

    @model_validator(mode="after")
    def _valida_nomes_de_coluna_unicos(self) -> Self:
        """Garante que não há colunas com o mesmo nome na mesma tabela."""
        nomes = [coluna.nome for coluna in self.colunas]
        duplicados = {nome for nome in nomes if nomes.count(nome) > 1}
        if duplicados:
            raise ValueError(f"Nomes de coluna duplicados: {sorted(duplicados)}.")
        return self

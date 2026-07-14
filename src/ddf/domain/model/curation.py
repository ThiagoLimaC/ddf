"""Curation Context — estrutura extraída enriquecida com curadoria humana."""

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado


class ColunaCurada(BaseModel):
    """Coluna extraída acrescida de curadoria humana."""

    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    tabela_referenciada: str | None = None
    coluna_referenciada: str | None = None
    papel_de_negocio: str | None = Field(
        default=None,
        description="Descrição semântica do que a coluna representa para o negócio.",
    )
    regras_de_negocio: list[str] = Field(
        default_factory=list,
        description="Restrições/invariantes de negócio da coluna, em texto livre.",
    )

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


class TabelaCurada(BaseModel):
    """Tabela extraída acrescida de curadoria humana."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaCurada]
    total_linhas: int = Field(ge=0)
    papel_de_negocio: str | None = Field(
        default=None,
        description="Descrição semântica do que a tabela representa para o negócio.",
    )
    regras_de_negocio: list[str] = Field(
        default_factory=list,
        description="Restrições/invariantes de negócio da tabela, em texto livre.",
    )
    amostra: pl.DataFrame | None
    metadados_amostra: MetadadosDeAmostra

    @model_validator(mode="after")
    def _valida_nomes_de_coluna_unicos(self) -> Self:
        """Garante que não há colunas com o mesmo nome na mesma tabela."""
        nomes = [coluna.nome for coluna in self.colunas]
        duplicados = {nome for nome in nomes if nomes.count(nome) > 1}
        if duplicados:
            raise ValueError(f"Nomes de coluna duplicados: {sorted(duplicados)}.")
        return self


class BancoCurado(BaseModel):
    """Agregado do Curation Context — conjunto de tabelas curadas."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tabelas: list[TabelaCurada]

    @model_validator(mode="after")
    def _valida_tabelas_unicas(self) -> Self:
        """Garante que não há tabelas duplicadas (mesmo escopo + nome) no banco."""
        chaves = [(t.nome_escopo, t.nome_tabela) for t in self.tabelas]
        duplicadas = {chave for chave in chaves if chaves.count(chave) > 1}
        if duplicadas:
            raise ValueError(f"Tabelas duplicadas no banco: {sorted(duplicadas)}.")
        return self

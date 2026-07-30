"""Curation Context — estrutura extraída enriquecida com curadoria humana."""

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import TipoDeDado


class ColunaCurada(BaseModel):
    """Coluna extraída acrescida de curadoria humana."""

    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    referencia: ReferenciaDeColuna | None = None
    nao_nulavel: bool = Field(
        default=False,
        description=(
            "NOT NULL real do schema — garantia da fonte, não estimativa amostral."
        ),
    )
    unica: bool = Field(
        default=False,
        description=(
            "UNIQUE single-column real do schema (PK excluída). Constraints "
            "UNIQUE compostas de 2+ colunas não marcam nenhuma coluna "
            "individual como única — esse caso fica deliberadamente fora de "
            "representação."
        ),
    )
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
        if self.chave_estrangeira and self.referencia is None:
            raise ValueError("chave_estrangeira=True exige referencia preenchida.")
        if not self.chave_estrangeira and self.referencia is not None:
            raise ValueError("referencia só faz sentido com chave_estrangeira=True.")
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
    restricoes_unicas: list[RestricaoUnica] = Field(
        default_factory=list,
        description=(
            "UNIQUE composto (2+ colunas) real do schema. UNIQUE "
            "single-column continua representado por ColunaCurada.unica."
        ),
    )
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(
        default_factory=list,
        description=(
            "FK composta (2+ colunas locais) real do schema, agrupada por "
            "constraint. FK de coluna única continua representada por "
            "ColunaCurada.referencia."
        ),
    )

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

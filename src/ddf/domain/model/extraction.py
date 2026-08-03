"""Extraction Context — estrutura crua da fonte de dados, sem curadoria."""

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import TipoDeDado


class ColunaExtraida(BaseModel):
    """Coluna de uma tabela, tal como extraída da fonte, sem curadoria."""

    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    referencias: list[ReferenciaDeColuna] = Field(
        default_factory=list,
        description=(
            "Uma entrada por constraint FK de coluna única que referencia "
            "esta coluna — pode ter 2+ quando a coluna é FK polimórfica "
            "(2+ constraints distintas apontando pra tabelas diferentes). "
            "FK composta (2+ colunas locais numa mesma constraint) não "
            "aparece aqui, ver TabelaExtraida.restricoes_fk_compostas."
        ),
    )
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

    @model_validator(mode="after")
    def _valida_referencia_de_chave_estrangeira(self) -> Self:
        """Garante que chave_estrangeira e as referências de destino andam juntas."""
        if self.chave_estrangeira and not self.referencias:
            raise ValueError("chave_estrangeira=True exige ao menos uma referência.")
        if not self.chave_estrangeira and self.referencias:
            raise ValueError("referencias só faz sentido com chave_estrangeira=True.")
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
    restricoes_unicas: list[RestricaoUnica] = Field(
        default_factory=list,
        description=(
            "UNIQUE composto (2+ colunas) real do schema. UNIQUE "
            "single-column continua representado por ColunaExtraida.unica."
        ),
    )
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(
        default_factory=list,
        description=(
            "FK composta (2+ colunas locais) real do schema, agrupada por "
            "constraint. FK de coluna única continua representada por "
            "ColunaExtraida.referencias."
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

    @model_validator(mode="after")
    def _valida_colunas_das_restricoes_unicas(self) -> Self:
        """Garante que toda coluna citada em restricoes_unicas existe na tabela."""
        nomes_das_colunas = {coluna.nome for coluna in self.colunas}
        for restricao in self.restricoes_unicas:
            desconhecidas = set(restricao.colunas) - nomes_das_colunas
            if desconhecidas:
                raise ValueError(
                    f"RestricaoUnica cita coluna(s) inexistente(s) na tabela: "
                    f"{sorted(desconhecidas)}."
                )
        return self

    @model_validator(mode="after")
    def _valida_colunas_das_restricoes_fk_compostas(self) -> Self:
        """Garante que toda coluna local citada em restricoes_fk_compostas existe."""
        nomes_das_colunas = {coluna.nome for coluna in self.colunas}
        for restricao in self.restricoes_fk_compostas:
            desconhecidas = set(restricao.colunas_locais) - nomes_das_colunas
            if desconhecidas:
                raise ValueError(
                    f"RestricaoDeFkComposta cita coluna(s) local(is) "
                    f"inexistente(s) na tabela: {sorted(desconhecidas)}."
                )
        return self

"""Analysis Context — métricas calculadas sobre a estrutura curada."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.curation import BancoCurado


class MetricaDeColuna(BaseModel):
    """Value Object base para métricas calculadas sobre uma coluna."""

    model_config = ConfigDict(frozen=True)

    origem: str


class MetricasBaseColuna(MetricaDeColuna):
    """Métricas de coluna produzidas por AnalisadorDeMetricasDeColuna."""

    origem: str = "AnalisadorDeMetricasDeColuna"
    percentual_nulo: float = Field(ge=0, le=100)
    percentual_unico: float = Field(ge=0, le=100)
    valores_frequentes: list[tuple[str, int]] = Field(max_length=10)
    minimo: str | None = None
    maximo: str | None = None
    formato_detectado: str | None = None


class MetricaDeTabela(BaseModel):
    """Value Object base para métricas calculadas sobre uma tabela."""

    model_config = ConfigDict(frozen=True)

    origem: str


class MetricasBaseTabela(MetricaDeTabela):
    """Métricas de tabela produzidas por AnalisadorDeMetricasDeTabela."""

    origem: str = "AnalisadorDeMetricasDeTabela"
    completude: float = Field(ge=0, le=100)


TipoDeMetrica = type[MetricaDeColuna] | type[MetricaDeTabela]
"""Tipo de métrica declarado em `produz`/`requer` de Analisador e Gerador."""


class ColunaAnalisada(BaseModel):
    """Coluna curada acrescida das métricas calculadas pelos Analisadores."""

    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    referencia: ReferenciaDeColuna | None = None
    papel_de_negocio: str | None = None
    regras_de_negocio: list[str] = Field(default_factory=list)
    metricas: list[MetricaDeColuna] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valida_referencia_de_chave_estrangeira(self) -> Self:
        """Garante que chave_estrangeira e a referência de destino andam juntas."""
        if self.chave_estrangeira and self.referencia is None:
            raise ValueError("chave_estrangeira=True exige referencia preenchida.")
        if not self.chave_estrangeira and self.referencia is not None:
            raise ValueError("referencia só faz sentido com chave_estrangeira=True.")
        return self


class TabelaAnalisada(BaseModel):
    """Tabela curada acrescida das métricas calculadas pelos Analisadores."""

    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaAnalisada]
    total_linhas: int = Field(ge=0)
    papel_de_negocio: str | None = None
    regras_de_negocio: list[str] = Field(default_factory=list)
    metadados_amostra: MetadadosDeAmostra
    metricas: list[MetricaDeTabela] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valida_nomes_de_coluna_unicos(self) -> Self:
        """Garante que não há colunas com o mesmo nome na mesma tabela."""
        nomes = [coluna.nome for coluna in self.colunas]
        duplicados = {nome for nome in nomes if nomes.count(nome) > 1}
        if duplicados:
            raise ValueError(f"Nomes de coluna duplicados: {sorted(duplicados)}.")
        return self


class BancoAnalisado(BaseModel):
    """Agregado do Analysis Context — conjunto de tabelas analisadas."""

    tabelas: list[TabelaAnalisada]

    @model_validator(mode="after")
    def _valida_tabelas_unicas(self) -> Self:
        """Garante que não há tabelas duplicadas (mesmo escopo + nome) no banco."""
        chaves = [(t.nome_escopo, t.nome_tabela) for t in self.tabelas]
        duplicadas = {chave for chave in chaves if chaves.count(chave) > 1}
        if duplicadas:
            raise ValueError(f"Tabelas duplicadas no banco: {sorted(duplicadas)}.")
        return self


class ContextoDeAnalise(BaseModel):
    """Entrada/saída de cada Analisador — combina dados curados e métricas."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    curado: BancoCurado
    analisado: BancoAnalisado


def iniciar_contexto(curado: BancoCurado) -> ContextoDeAnalise:
    """Cria ContextoDeAnalise com BancoAnalisado vazio a partir do BancoCurado."""
    tabelas = [
        TabelaAnalisada(
            **tabela.model_dump(exclude={"colunas", "amostra"}),
            colunas=[
                ColunaAnalisada.model_validate(coluna.model_dump())
                for coluna in tabela.colunas
            ],
        )
        for tabela in curado.tabelas
    ]
    return ContextoDeAnalise(
        curado=curado,
        analisado=BancoAnalisado(tabelas=tabelas),
    )

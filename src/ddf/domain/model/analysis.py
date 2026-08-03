"""Analysis Context — métricas calculadas sobre a estrutura curada."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
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
    referencias: list[ReferenciaDeColuna] = Field(
        default_factory=list,
        description=(
            "Uma entrada por constraint FK de coluna única que referencia "
            "esta coluna — pode ter 2+ quando a coluna é FK polimórfica "
            "(2+ constraints distintas apontando pra tabelas diferentes). "
            "FK composta (2+ colunas locais numa mesma constraint) não "
            "aparece aqui, ver TabelaAnalisada.restricoes_fk_compostas."
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
    papel_de_negocio: str | None = None
    regras_de_negocio: list[str] = Field(default_factory=list)
    metricas: list[MetricaDeColuna] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valida_referencia_de_chave_estrangeira(self) -> Self:
        """Garante que chave_estrangeira e as referências de destino andam juntas."""
        if self.chave_estrangeira and not self.referencias:
            raise ValueError("chave_estrangeira=True exige ao menos uma referência.")
        if not self.chave_estrangeira and self.referencias:
            raise ValueError("referencias só faz sentido com chave_estrangeira=True.")
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
    restricoes_unicas: list[RestricaoUnica] = Field(
        default_factory=list,
        description=(
            "UNIQUE composto (2+ colunas) real do schema. UNIQUE "
            "single-column continua representado por ColunaAnalisada.unica."
        ),
    )
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(
        default_factory=list,
        description=(
            "FK composta (2+ colunas locais) real do schema, agrupada por "
            "constraint. FK de coluna única continua representada por "
            "ColunaAnalisada.referencias."
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

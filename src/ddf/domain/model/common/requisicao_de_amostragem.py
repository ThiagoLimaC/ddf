"""O que uma EstrategiaDeAmostragem pede para um Extrator executar."""

from pydantic import BaseModel, ConfigDict, Field


class AmostragemProbabilistica(BaseModel):
    """Amostra `percentual`% das linhas, sujeita a viés de ruído estatístico.

    `seed`, quando informado, torna a amostragem reprodutível — cada
    Extrator repassa o mesmo valor para o mecanismo nativo do próprio
    dialeto (`TABLESAMPLE ... REPEATABLE`, `RAND(seed)`).
    """

    model_config = ConfigDict(frozen=True)

    percentual: float = Field(gt=0, le=100)
    seed: int | None = None


class AmostragemIntegral(BaseModel):
    """Lê a tabela inteira, sem nenhum mecanismo probabilístico de amostragem."""

    model_config = ConfigDict(frozen=True)


class RequisicaoPorFaixa(BaseModel):
    """Amostra `percentual`% das linhas por faixas contíguas, não linha a linha.

    Custo de leitura escala com `percentual`, não com o total de linhas da
    tabela — ao contrário de `AmostragemProbabilistica`. Em troca, sujeita a
    viés de cluster: linhas de uma mesma faixa contígua tendem a ser
    semelhantes (ex.: inseridas na mesma janela de tempo), o que pode
    distorcer `percentual_nulo`/`percentual_unico`/`valores_frequentes`
    calculados sobre a amostra. `seed`, quando informado, torna a escolha
    das faixas reprodutível — cada Extrator repassa o mesmo valor para o
    mecanismo nativo do próprio dialeto.
    """

    model_config = ConfigDict(frozen=True)

    percentual: float = Field(gt=0, le=100)
    seed: int | None = None


RequisicaoDeAmostragem = (
    AmostragemProbabilistica | AmostragemIntegral | RequisicaoPorFaixa
)

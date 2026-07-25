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


RequisicaoDeAmostragem = AmostragemProbabilistica | AmostragemIntegral

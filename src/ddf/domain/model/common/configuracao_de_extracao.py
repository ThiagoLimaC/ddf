"""Configuração de extração compartilhada por todos os Extratores."""

from pydantic import BaseModel, Field, InstanceOf, model_validator

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem


class ConfiguracaoDeExtracao(BaseModel):
    """Parâmetros que controlam como a extração paralela é executada."""

    estrategia: InstanceOf[EstrategiaDeAmostragem]
    max_trabalhadores: int = Field(default=8, gt=0)
    max_conexoes: int = Field(default=10, gt=0)

    @model_validator(mode="after")
    def _valida_max_conexoes(self) -> "ConfiguracaoDeExtracao":
        """Garante que há conexões suficientes para todos os trabalhadores."""
        if self.max_conexoes < self.max_trabalhadores:
            raise ValueError(
                "max_conexoes deve ser >= max_trabalhadores "
                f"({self.max_conexoes} < {self.max_trabalhadores})"
            )
        return self

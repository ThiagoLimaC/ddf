"""Port para adaptadores concretos que calculam métricas sobre o banco curado."""

from typing import Protocol, runtime_checkable

from ddf.domain.model.analysis import ContextoDeAnalise, TipoDeMetrica
from ddf.domain.shared.resultado import Resultado


@runtime_checkable
class Analisador(Protocol):
    """Calcula métricas sobre um ContextoDeAnalise e as acrescenta ao BancoAnalisado."""

    produz: list[TipoDeMetrica]
    requer: list[TipoDeMetrica]

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
        """Executa o Analisador sobre o ContextoDeAnalise recebido."""
        ...

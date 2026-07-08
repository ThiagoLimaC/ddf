"""Port para adaptadores concretos que produzem artefatos a partir do BancoAnalisado."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ddf.domain.model.analysis import BancoAnalisado, TipoDeMetrica
from ddf.domain.shared.resultado import Resultado


@runtime_checkable
class Gerador(Protocol):
    """Gera um artefato de saída a partir do BancoAnalisado."""

    requer: list[TipoDeMetrica]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Escreve o artefato correspondente em destino."""
        ...

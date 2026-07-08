"""Port para coordenação paralela de extração e aplicação de sobrescritas."""

from typing import Protocol, runtime_checkable

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Resultado
from ddf.pipeline.estagio import Estagio


@runtime_checkable
class OrquestradorDeTabelas(Protocol):
    """Coordena a extração e curadoria de tabelas em duas fases paralelas."""

    def extrair(
        self,
        schemas: list[str],
        extrator: Extrator,
    ) -> Resultado[list[TabelaExtraida]]:
        """Extrai, em paralelo, todas as tabelas dos schemas informados."""
        ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]:
        """Aplica, em paralelo, a Sobrescrita sobre cada TabelaExtraida."""
        ...

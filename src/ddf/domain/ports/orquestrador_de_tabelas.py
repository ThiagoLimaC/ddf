"""Port para coordenação paralela de extração e aplicação de sobrescritas."""

from collections.abc import Callable
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
        escopos: list[str],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Extrai, em paralelo, todas as tabelas dos escopos informados.

        Falhas individuais (listagem de um escopo ou extração de uma tabela)
        nunca abortam o lote inteiro — viram Aviso no Sucesso devolvido,
        junto das tabelas que deram certo.
        """
        ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Aplica, em paralelo, a Sobrescrita sobre cada TabelaExtraida.

        Falhas individuais nunca abortam o lote inteiro — viram Aviso no
        Sucesso devolvido, junto das tabelas cuja sobrescrita deu certo.
        """
        ...

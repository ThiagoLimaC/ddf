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
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Extrai, em paralelo, as tabelas identificadas pelos pares informados.

        `pares` já vem pronto — (escopo, tabela) por item, na forma que
        `Extrator.listar_tabelas` devolve. Este Port não lista nada por
        conta própria: quem chama já decidiu o subconjunto e já sabe o
        total (`len(pares)`), sem precisar de callback.

        `pares` vazio é aceito sem distinção de motivo — decidir se um lote
        vazio deve abortar o fluxo é responsabilidade de quem chama, não
        deste Port.

        Falha ao extrair uma tabela nunca aborta o lote inteiro — vira
        Aviso no Sucesso devolvido, junto das tabelas que deram certo.
        """
        ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Aplica, em paralelo, a Sobrescrita sobre cada TabelaExtraida.

        Falhas individuais nunca abortam o lote inteiro — viram Aviso no
        Sucesso devolvido, junto das tabelas cuja sobrescrita deu certo.
        """
        ...

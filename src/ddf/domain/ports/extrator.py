"""Port para adaptadores concretos de extração de dados de uma fonte."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.resultado import Resultado


@runtime_checkable
class Extrator(Protocol):
    """Extrai estrutura e amostra de tabelas de uma fonte de dados concreta."""

    def listar_escopos(self) -> Resultado[list[str]]:
        """Lista os escopos disponíveis na fonte, ordenados por nome."""
        ...

    def listar_tabelas(self, escopo: str, /) -> Resultado[list[tuple[str, str]]]:
        """Lista (escopo, nome_tabela) do escopo informado, ordenado por nome_tabela."""
        ...

    def extrair_tabela(self, escopo: str, tabela: str, /) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        ...


@dataclass(frozen=True)
class ExtratorRegistrado:
    """Um Extrator registrado, junto da função que sabe construí-lo interativamente.

    Alvo do entry point do grupo "ddf.extratores" — um plugin de terceiro
    expõe uma instância deste tipo (não só a classe do Extrator), porque o
    construtor de um Extrator concreto normalmente precisa perguntar
    credenciais/parâmetros específicos da fonte de forma interativa,
    responsabilidade que `construir` encapsula.
    """

    classe_extrator: type[Extrator]
    construir: Callable[[ConfiguracaoDeExtracao], Extrator]

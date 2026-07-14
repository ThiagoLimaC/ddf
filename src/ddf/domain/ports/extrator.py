"""Port para adaptadores concretos de extração de dados de uma fonte."""

from typing import Protocol, runtime_checkable

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

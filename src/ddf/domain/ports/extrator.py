"""Port para adaptadores concretos de extração de dados de uma fonte."""

from typing import Protocol, runtime_checkable

from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.resultado import Resultado


@runtime_checkable
class Extrator(Protocol):
    """Extrai estrutura e amostra de tabelas de uma fonte de dados concreta."""

    def listar_tabelas(self, schema: str) -> Resultado[list[tuple[str, str]]]:
        """Lista (schema, nome_tabela) do schema informado, ordenado por nome_tabela."""
        ...

    def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Extrai estrutura, amostra e metadados de uma tabela específica."""
        ...

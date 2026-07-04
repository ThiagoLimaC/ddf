"""Port para estratégias plugáveis de amostragem de tabelas."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EstrategiaDeAmostragem(Protocol):
    """Controla a consulta usada para amostrar dados de uma tabela."""

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        ...

    def consulta(self, schema: str, tabela: str) -> str:
        """Retorna a SQL de amostragem para a tabela especificada."""
        ...

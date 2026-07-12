"""Port para políticas plugáveis de amostragem de tabelas."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EstrategiaDeAmostragem(Protocol):
    """Descreve quanto amostrar de cada tabela, sem saber como executar isso.

    Traduzir a política em uma consulta concreta é responsabilidade de cada
    Extrator (já acoplado ao dialeto SQL da própria fonte de dados) — este
    Port nunca gera SQL, para não amarrar a política de amostragem a nenhum
    banco específico.
    """

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        ...

    @property
    def percentual(self) -> float:
        """Retorna a fração da tabela a amostrar, em porcentagem (0, 100]."""
        ...

"""Port para políticas plugáveis de amostragem de tabelas."""

from typing import Protocol, runtime_checkable

from ddf.domain.model.common.requisicao_de_amostragem import RequisicaoDeAmostragem


@runtime_checkable
class EstrategiaDeAmostragem(Protocol):
    """Descreve quanto amostrar de cada tabela, sem saber como executar isso.

    Traduzir a política em uma consulta concreta é responsabilidade de cada
    Extrator (já acoplado ao dialeto SQL da própria fonte de dados) — este
    Port nunca gera SQL, para não amarrar a política de amostragem a nenhum
    banco específico.

    **Custo de execução é responsabilidade de cada `Extrator`, não deste
    Port** — a política aqui descreve só "quanto" amostrar, nunca "quão
    caro" é fazer isso num motor específico. Ver `PercentualDeLinhas` para
    a limitação de custo conhecida da implementação padrão.
    """

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        ...

    @property
    def requisicao(self) -> RequisicaoDeAmostragem:
        """Retorna o que amostrar — cada Extrator decide como, no dialeto próprio."""
        ...

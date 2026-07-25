"""Política de amostragem que lê a tabela inteira, sem mecanismo probabilístico."""

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemIntegral


class FullScan:
    """Descreve uma leitura completa da tabela — a amostra é a tabela inteira.

    Diferente de `PercentualDeLinhas(percentual=100)`, não passa por
    `TABLESAMPLE`/`RAND()` — cada Extrator monta um `SELECT *` puro. O
    resultado prático das duas é equivalente (`TABLESAMPLE BERNOULLI(100)`/
    `RAND() <= 1` incluem cada linha com probabilidade 1), mas `FullScan`
    deixa a intenção "quero a tabela inteira" explícita no artefato gerado
    (`metadados_amostra.estrategia == "full_scan"`), sem depender de quem lê
    saber que percentual=100 é o caso especial que produz o mesmo resultado.
    """

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        return "full_scan"

    @property
    def requisicao(self) -> AmostragemIntegral:
        """Retorna AmostragemIntegral() — sem parâmetros, não há o que configurar."""
        return AmostragemIntegral()

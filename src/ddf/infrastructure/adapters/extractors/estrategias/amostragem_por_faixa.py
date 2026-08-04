"""Política de amostragem opt-in: percentual das linhas, lido por faixas contíguas."""

from ddf.domain.model.common.requisicao_de_amostragem import RequisicaoPorFaixa


class AmostragemPorFaixa:
    """Descreve uma amostra de `percentual`% das linhas, lida por faixas contíguas.

    Diferente de `PercentualDeLinhas`, o custo de leitura escala com
    `percentual`, não com o total de linhas da tabela — cada Extrator traduz
    isso para um mecanismo que evita varredura sequencial completa no
    próprio dialeto (ex.: `TABLESAMPLE SYSTEM` no Postgres, faixas de chave
    primária no MariaDB). Em troca, sujeita a viés de cluster: linhas de uma
    mesma faixa contígua tendem a ser semelhantes, o que pode distorcer
    métricas calculadas sobre a amostra. Por isso é opt-in — nunca troca
    silenciosa do default (`PercentualDeLinhas`) — e todo Extrator emite um
    `Aviso` explicando o viés em toda extração que a usa.
    """

    def __init__(self, percentual: float, seed: int | None = None) -> None:
        """Levanta ValidationError se `percentual` não estiver em (0, 100].

        Args:
            percentual: fração da tabela a amostrar, em porcentagem (ex.: 5.0
                para 5%). Escala com o tamanho de cada tabela — cada Extrator
                decide como aplicar isso no dialeto SQL da própria fonte.
            seed: valor fixo para tornar a escolha das faixas reprodutível
                entre execuções. Sem seed (padrão), cada execução amostra
                faixas diferentes.
        """
        self._requisicao = RequisicaoPorFaixa(percentual=percentual, seed=seed)

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        return "amostragem_por_faixa"

    @property
    def requisicao(self) -> RequisicaoPorFaixa:
        """Retorna o percentual e o seed configurados, como RequisicaoPorFaixa."""
        return self._requisicao

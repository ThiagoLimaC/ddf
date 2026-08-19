"""Política de amostragem padrão: percentual das linhas de cada tabela."""

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemProbabilistica


class PercentualDeLinhas:
    """Descreve uma amostra de `percentual`% das linhas de cada tabela.

    **Limitação de custo conhecida** tanto `TABLESAMPLE
    BERNOULLI` (`ExtratorPostgres`) quanto `WHERE RAND() <= p`
    (`ExtratorMariaDB`) fazem varredura sequencial completa da tabela,
    independente do `percentual` pedido — o custo escala com `total_linhas`
    da tabela, não com o tamanho da amostra resultante. `percentual=1.0`
    numa tabela de 50 milhões de linhas continua lendo as 50 milhões, só
    descarta a maioria após ler. Relevante pra NFR9 do PRD ("dezenas ou
    centenas de tabelas... tempo razoável") em bancos com tabelas muito
    grandes — não há forma de amostrar sem varredura completa nesses dois
    motores sem um índice específico para isso. Avisado uma vez, no momento
    em que o usuário escolhe esta estratégia no wizard
    (`cli/registro/estrategias.py::_construir_percentual_de_linhas`) — não
    mais como um `Aviso` por tabela via `construir_metadados_de_amostra`
    (comportamento anterior): o fato é estrutural e idêntico em qualquer
    tabela/execução, então repeti-lo a cada tabela extraída só virava ruído.
    """

    def __init__(self, percentual: float, seed: int | None = None) -> None:
        """Levanta ValidationError se `percentual` não estiver em (0, 100].

        Args:
            percentual: fração da tabela a amostrar, em porcentagem (ex.: 5.0
                para 5%). Escala com o tamanho de cada tabela — cada Extrator
                decide como aplicar isso no dialeto SQL da própria fonte.
            seed: valor fixo para tornar a amostragem reprodutível entre
                execuções. Sem seed (padrão), cada execução amostra linhas
                diferentes.
        """
        self._requisicao = AmostragemProbabilistica(percentual=percentual, seed=seed)

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        return "percentual_de_linhas"

    @property
    def requisicao(self) -> AmostragemProbabilistica:
        """Retorna o percentual e o seed configurados, como AmostragemProbabilistica."""
        return self._requisicao

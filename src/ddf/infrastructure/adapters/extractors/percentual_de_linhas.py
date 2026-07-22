"""Política de amostragem padrão: percentual das linhas de cada tabela."""


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
    motores sem um índice específico para isso.
    """

    def __init__(self, percentual: float) -> None:
        """Levanta ValueError se `percentual` não estiver em (0, 100].

        Args:
            percentual: fração da tabela a amostrar, em porcentagem (ex.: 5.0
                para 5%). Escala com o tamanho de cada tabela — cada Extrator
                decide como aplicar isso no dialeto SQL da própria fonte.
        """
        if not (0 < percentual <= 100):
            raise ValueError(f"percentual deve estar em (0, 100] ({percentual}).")
        self._percentual = percentual

    @property
    def nome(self) -> str:
        """Retorna o identificador usado em MetadadosDeAmostra.estrategia."""
        return "percentual_de_linhas"

    @property
    def percentual(self) -> float:
        """Retorna a fração da tabela a amostrar, em porcentagem (0, 100]."""
        return self._percentual

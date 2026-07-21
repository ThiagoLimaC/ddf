"""Cálculos de métrica compartilhados entre Geradores.

Extraído de `gerador_dbt.py` (issue #44/#15) porque a mesma pergunta
estatística — "os top-10 `valores_frequentes` cobrem o suficiente da amostra
não-nula pra confiar na enumeração?" — passou a ser usada por dois Geradores
(`GeradorDbt` para `accepted_values`, `GeradorContextoDeIA` para sugestão de
filtro `enum`), e duplicar a lógica/constante em dois arquivos arriscaria os
dois divergirem silenciosamente no futuro.
"""

from ddf.domain.model.analysis import MetricasBaseColuna

_COBERTURA_MINIMA_ACCEPTED_VALUES = 0.9


def _cobertura_dos_valores_frequentes(
    metrica: MetricasBaseColuna, tamanho_amostra: int
) -> float:
    """Fração dos valores não-nulos da amostra que os top-10 de fato cobrem.

    `accepted_values` testa enumeração exaustiva contra a população real,
    mas `valores_frequentes` só enxerga os 10 valores mais comuns **entre os
    não-nulos** da amostra (`AnalisadorDeMetricasDeColuna` calcula sobre
    `serie.drop_nulls()`). Quando esses 10 já respondem por quase todo o
    universo não-nulo, sobra pouco espaço pra um valor de cauda longa
    desconhecido aparecer na população; quando cobrem uma fração pequena, a
    lista é só a ponta do iceberg e sugerir o teste seria enumerar um
    universo que não foi visto. O denominador é o **não-nulo** da amostra,
    não o total — dividir pelo total penalizaria injustamente uma coluna
    categórica com muitos nulos cujos valores presentes já são exaustivos.

    Args:
        metrica: métricas de coluna já calculadas.
        tamanho_amostra: total de linhas amostradas da tabela (com nulos).

    Returns:
        Contagem somada dos `valores_frequentes` dividida pelo total de
        valores não-nulos da amostra, ou `0.0` se não houver nenhum valor
        não-nulo (amostra vazia ou coluna inteiramente nula).
    """
    nao_nulos_na_amostra = tamanho_amostra * (1 - metrica.percentual_nulo / 100)
    if nao_nulos_na_amostra <= 0:
        return 0.0
    total_capturado = sum(contagem for _, contagem in metrica.valores_frequentes)
    return total_capturado / nao_nulos_na_amostra

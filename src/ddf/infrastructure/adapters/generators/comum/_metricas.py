"""Cálculos de métrica compartilhados entre Geradores.

Extraído de `gerador_dbt.py` (issue #44/#15) porque a mesma pergunta
estatística — "os top-10 `valores_frequentes` cobrem o suficiente da amostra
não-nula pra confiar na enumeração?" — passou a ser usada por dois Geradores
(`GeradorDbt` para `accepted_values`, `GeradorContextoDeIA` para sugestão de
filtro `enum`), e duplicar a lógica/constante em dois arquivos arriscaria os
dois divergirem silenciosamente no futuro.

**Issue #95:** os dois Geradores decidiam "isso é categórico o suficiente"
só por `percentual_unico < 10.0` + cobertura — sem piso de amostra nem
exclusão por tipo, e cada um aplicava esses critérios de forma levemente
diferente. Isso gerou falso positivo real contra um banco de teste
(`criado_em` TIMESTAMP, `produto_codigo` código de catálogo crescente,
`quantidade` INTEGER com baixa cardinalidade só na amostra).
`_elegivel_para_enumeracao` centraliza os critérios adicionais nos dois
Geradores, pelo mesmo motivo que motivou a extração original.
"""

from ddf.domain.model.analysis import ColunaAnalisada, MetricasBaseColuna
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado

_COBERTURA_MINIMA_ACCEPTED_VALUES = 0.9

_TAMANHO_AMOSTRA_MINIMO_ENUMERACAO = 100
"""Piso de amostra abaixo do qual nenhuma coluna é tratada como enumerável.

Mesmo valor já usado pelo `AnalisadorDeMetricasDeColuna` para emitir Aviso de
baixo sinal — sem esse piso, uma amostra pequena pode parecer 100%
categórica só por coincidência de tamanho.
"""

_CARDINALIDADE_MAXIMA_ACCEPTED_VALUES = 10
"""Teto de valores distintos na amostra para uma coluna ser enumerável.

`valores_frequentes` só guarda os top-10 — sem um teto sobre a contagem real
de distintos (reconstruída via `_contagem_de_distintos`, não o tamanho da
lista truncada), uma coluna com 200 valores distintos concentrados nos 10
mais frequentes passaria na checagem de cobertura como se fosse exaustiva.
"""

_CATEGORIAS_EXCLUIDAS_DE_ENUMERACAO = frozenset(
    {
        CategoriaDeDado.TIMESTAMP,
        CategoriaDeDado.DATE,
        CategoriaDeDado.TIME,
        CategoriaDeDado.UUID,
        CategoriaDeDado.JSON,
        CategoriaDeDado.ARRAY,
    }
)
"""Categorias nunca tratadas como enumeráveis, independente de métrica.

`TIMESTAMP`/`DATE`/`TIME` são monotônicas por natureza — nenhuma amostra
torna um "criado em" um universo fechado. `UUID` é defesa barata (identidade,
nunca categoria). `JSON`/`ARRAY` são semanticamente incompatíveis com
`accepted_values`/enum. Deliberadamente **sem** `INTEGER`/`NUMERIC` em
bloco — `quantidade`/`status_code`/`rating` podem ser categóricos de
verdade; o problema desses é piso de amostra, não o tipo.
"""


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


def _contagem_de_distintos(metrica: MetricasBaseColuna, tamanho_amostra: int) -> int:
    """Reconstrói o nº exato de valores distintos não-nulos na amostra inteira.

    `valores_frequentes` só guarda os top-10 — contar `len(valores_frequentes)`
    não distingue "a coluna tem exatamente 10 distintos" de "tem 200 e só
    vemos os 10 mais frequentes". `percentual_unico`, ao contrário, já é
    `distintos_não_nulos / tamanho_amostra * 100` sobre a amostra inteira
    (`AnalisadorDeMetricasDeColuna._construir_metricas_de_coluna`), então a
    contagem real é só desfazer essa divisão: `distintos = percentual_unico
    * tamanho_amostra / 100`. Não multiplicar de novo pela fração de
    não-nulos — o denominador de `percentual_unico` já é o total, não o
    não-nulo; fazer isso de novo subestima a contagem sempre que há nulos
    (ex.: 90% nulos e 60 distintos reais vira `6`, não `60`).

    Args:
        metrica: métricas de coluna já calculadas.
        tamanho_amostra: total de linhas amostradas da tabela (com nulos).

    Returns:
        Nº de valores distintos entre os não-nulos da amostra, arredondado.
    """
    return round(tamanho_amostra * metrica.percentual_unico / 100)


def _elegivel_para_enumeracao(
    coluna: ColunaAnalisada, metrica: MetricasBaseColuna | None, tamanho_amostra: int
) -> bool:
    """Decide se uma coluna sustenta enumeração fechada (accepted_values/enum).

    Cinco critérios, todos obrigatórios (issue #95 — corrige falso positivo
    real contra um banco de teste em `criado_em` TIMESTAMP, `produto_codigo`
    código de catálogo crescente e `quantidade` INTEGER de baixa cardinalidade
    só na amostra):

    1. `coluna.tipo_dado.categoria` fora de `_CATEGORIAS_EXCLUIDAS_DE_ENUMERACAO`.
    2. `tamanho_amostra >= _TAMANHO_AMOSTRA_MINIMO_ENUMERACAO`.
    3. Contagem de distintos (`_contagem_de_distintos`, não o tamanho da lista
       truncada) menor que `_CARDINALIDADE_MAXIMA_ACCEPTED_VALUES`.
    4. `percentual_unico < 10.0` — sinal de baixa cardinalidade relativa.
    5. Cobertura dos top-10 `valores_frequentes` (`_cobertura_dos_valores_frequentes`)
       maior ou igual a `_COBERTURA_MINIMA_ACCEPTED_VALUES`.

    Não checa `chave_primaria` — cada chamador decide se isso importa pro
    próprio caso de uso (o `GeradorDbt` suprime `unique`/`not_null` para PK,
    mas `accepted_values` nunca fez sentido pra PK de qualquer forma, já
    filtrado a montante por `percentual_unico` alto).

    Args:
        coluna: coluna analisada a avaliar.
        metrica: métricas de coluna já calculadas, ou `None` se ausentes.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        `True` se todos os critérios forem satisfeitos.
    """
    if metrica is None or not metrica.valores_frequentes:
        return False
    if coluna.tipo_dado.categoria in _CATEGORIAS_EXCLUIDAS_DE_ENUMERACAO:
        return False
    if tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_ENUMERACAO:
        return False
    distintos = _contagem_de_distintos(metrica, tamanho_amostra)
    if distintos >= _CARDINALIDADE_MAXIMA_ACCEPTED_VALUES:
        return False
    if metrica.percentual_unico >= 10.0:
        return False
    return _cobertura_dos_valores_frequentes(metrica, tamanho_amostra) >= (
        _COBERTURA_MINIMA_ACCEPTED_VALUES
    )

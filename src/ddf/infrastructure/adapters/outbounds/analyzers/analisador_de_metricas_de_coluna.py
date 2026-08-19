"""AnalisadorDeMetricasDeColuna: métricas descritivas por coluna via Polars."""

import polars as pl

from ddf.domain.model.analysis import (
    ColunaAnalisada,
    ContextoDeAnalise,
    MetricasBaseColuna,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import TabelaCurada
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.outbounds.analyzers.comum.detector_de_formato import (
    TETO_SUBAMOSTRA,
    detectar_formato,
)

_ORIGEM = "AnalisadorDeMetricasDeColuna"
_TAMANHO_AMOSTRA_MINIMO_AVISO = 100
_CATEGORIAS_COM_FORMATO = {CategoriaDeDado.VARCHAR, CategoriaDeDado.TEXT}
_SEED_SUBAMOSTRA_FORMATO = 20260804
"""Seed fixo da sub-amostragem de `detectar_formato` — não é o seed de
extração (`MetadadosDeAmostra.seed`, `None` em `TabelaInteira` e sem campo
pra registrar um valor gerado aqui). Fixo em vez de aleatório: garante
determinismo total, sempre a mesma sub-amostra pro mesmo dado de entrada."""


class AnalisadorDeMetricasDeColuna:
    """Calcula métricas descritivas de cada coluna a partir da amostra curada."""

    produz: list[TipoDeMetrica] = [MetricasBaseColuna]
    requer: list[TipoDeMetrica] = []

    def __call__(self, entrada: ContextoDeAnalise, /) -> Resultado[ContextoDeAnalise]:
        """Preenche MetricasBaseColuna de cada coluna e libera a amostra usada.

        Args:
            entrada: contexto com o BancoCurado (amostras Polars) e o
                BancoAnalisado acumulado até aqui. Não é modificado — o
                Analisador é sequencial hoje, mas devolve um contexto novo
                para não impor essa suposição a quem o chama (ver
                docs/system_design_doc.md, Decisão 11).

        Returns:
            Sucesso com um ContextoDeAnalise novo, `analisado` enriquecido
            com MetricasBaseColuna por coluna e `curado.tabelas[*].amostra`
            liberado, com um único Aviso agregado (tabelas e colunas
            afetadas, com o total analisado como denominador) se alguma
            tabela tiver amostra menor que 100 linhas — não um Aviso por
            tabela nem por coluna, para não assustar com uma lista longa
            numa análise com muitas tabelas pequenas. Falha apenas se
            curado e analisado estiverem fora de sincronia (violação de
            invariante estrutural, não erro de dado).
        """
        if len(entrada.curado.tabelas) != len(entrada.analisado.tabelas):
            return Falha(
                "ContextoDeAnalise inconsistente: quantidade de tabelas em "
                "curado e analisado não bate."
            )

        tabelas_com_amostra_pequena = 0
        colunas_com_amostra_pequena = 0
        total_colunas = 0
        novas_tabelas_curadas: list[TabelaCurada] = []
        novas_tabelas_analisadas: list[TabelaAnalisada] = []
        for tabela_curada, tabela_analisada in zip(
            entrada.curado.tabelas, entrada.analisado.tabelas, strict=True
        ):
            if len(tabela_curada.colunas) != len(tabela_analisada.colunas):
                return Falha(
                    "ContextoDeAnalise inconsistente: quantidade de colunas de "
                    f"'{tabela_curada.nome_escopo}.{tabela_curada.nome_tabela}' "
                    "não bate entre curado e analisado."
                )
            total_colunas += len(tabela_curada.colunas)
            nova_curada, nova_analisada, colunas_pequenas = _processar_tabela(
                tabela_curada, tabela_analisada
            )
            novas_tabelas_curadas.append(nova_curada)
            novas_tabelas_analisadas.append(nova_analisada)
            if colunas_pequenas:
                tabelas_com_amostra_pequena += 1
                colunas_com_amostra_pequena += colunas_pequenas

        novo_contexto = ContextoDeAnalise(
            curado=entrada.curado.model_copy(update={"tabelas": novas_tabelas_curadas}),
            analisado=entrada.analisado.model_copy(
                update={"tabelas": novas_tabelas_analisadas}
            ),
        )
        avisos: list[Aviso] = []
        if tabelas_com_amostra_pequena:
            total_tabelas = len(entrada.curado.tabelas)
            avisos.append(
                Aviso(
                    mensagem=(
                        f"Amostra pequena em {tabelas_com_amostra_pequena} de "
                        f"{total_tabelas} tabela(s): {colunas_com_amostra_pequena} "
                        f"de {total_colunas} coluna(s) com métricas potencialmente "
                        "pouco confiáveis (amostra menor que "
                        f"{_TAMANHO_AMOSTRA_MINIMO_AVISO} linhas)."
                    ),
                    origem=_ORIGEM,
                )
            )
        return Sucesso(novo_contexto, avisos=avisos)


def _processar_tabela(
    tabela_curada: TabelaCurada, tabela_analisada: TabelaAnalisada
) -> tuple[TabelaCurada, TabelaAnalisada, int]:
    """Calcula as métricas de todas as colunas de uma tabela e libera a amostra.

    Pré-condição: `tabela_curada.colunas` e `tabela_analisada.colunas` têm o
    mesmo tamanho — validado pelo chamador antes de invocar esta função.

    Args:
        tabela_curada: tabela curada, fonte da amostra Polars.
        tabela_analisada: tabela analisada, base das métricas calculadas.

    Returns:
        Uma nova TabelaCurada (amostra liberada), uma nova TabelaAnalisada
        (colunas com a métrica calculada acrescentada) e a quantidade de
        colunas cuja amostra tem menos de 100 linhas (0 se a tabela não for
        pequena) — o chamador agrega essa contagem num único Aviso global,
        em vez de um Aviso por tabela/coluna.
    """
    tamanho_amostra = tabela_curada.metadados_amostra.tamanho_amostra
    amostra = tabela_curada.amostra

    novas_colunas: list[ColunaAnalisada] = []
    for coluna_curada, coluna_analisada in zip(
        tabela_curada.colunas, tabela_analisada.colunas, strict=True
    ):
        if amostra is None or tamanho_amostra == 0 or amostra.height == 0:
            metrica = _metricas_vazias()
        else:
            serie = amostra[coluna_curada.nome]
            metrica = _calcular_metricas_coluna(
                serie, coluna_curada.tipo_dado, tamanho_amostra
            )
        novas_colunas.append(
            coluna_analisada.model_copy(
                update={"metricas": [*coluna_analisada.metricas, metrica]}
            )
        )

    colunas_com_amostra_pequena = (
        len(novas_colunas) if tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_AVISO else 0
    )

    nova_tabela_curada = tabela_curada.model_copy(update={"amostra": None})
    nova_tabela_analisada = tabela_analisada.model_copy(
        update={"colunas": novas_colunas}
    )
    return nova_tabela_curada, nova_tabela_analisada, colunas_com_amostra_pequena


def _metricas_vazias() -> MetricasBaseColuna:
    """Métricas para amostra ausente ou de tamanho zero, sem dividir por zero.

    Returns:
        MetricasBaseColuna com todos os campos numéricos zerados e os
        opcionais em None/lista vazia.
    """
    return MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=0.0,
        valores_frequentes=[],
        minimo=None,
        maximo=None,
        formato_detectado=None,
    )


def _calcular_metricas_coluna(
    serie: pl.Series, tipo_dado: TipoDeDado, tamanho_amostra: int
) -> MetricasBaseColuna:
    """Calcula as métricas de uma coluna a partir da amostra Polars.

    Args:
        serie: valores amostrados da coluna, incluindo nulos.
        tipo_dado: tipo de dado da coluna, usado para decidir se cabe
            detecção de formato.
        tamanho_amostra: total de linhas amostradas na tabela (> 0).

    Returns:
        MetricasBaseColuna com nulos excluídos de percentual_unico e
        valores_frequentes.
    """
    if serie.dtype.is_float():
        serie = serie.fill_nan(None)
    elif serie.dtype == pl.Object or serie.dtype.base_type() == pl.List:
        serie = _normalizar_serie_nao_nativa(serie)

    nao_nulos = serie.drop_nulls()

    minimo_bruto = serie.min()
    maximo_bruto = serie.max()

    formato_detectado = None
    if tipo_dado.categoria in _CATEGORIAS_COM_FORMATO:
        amostra_formato = nao_nulos
        if amostra_formato.len() > TETO_SUBAMOSTRA:
            amostra_formato = amostra_formato.sample(
                n=TETO_SUBAMOSTRA, seed=_SEED_SUBAMOSTRA_FORMATO, with_replacement=False
            )
        formato_detectado = detectar_formato(
            [str(valor) for valor in amostra_formato.to_list()]
        )

    return MetricasBaseColuna(
        percentual_nulo=serie.null_count() / tamanho_amostra * 100,
        percentual_unico=nao_nulos.n_unique() / tamanho_amostra * 100,
        valores_frequentes=_top_valores_frequentes(nao_nulos),
        minimo=str(minimo_bruto) if minimo_bruto is not None else None,
        maximo=str(maximo_bruto) if maximo_bruto is not None else None,
        formato_detectado=formato_detectado,
    )


def _normalizar_serie_nao_nativa(serie: pl.Series) -> pl.Series:
    """Stringifica uma Series de dtype Object ou List para liberar min/max/n_unique.

    `pl.Object` é o fallback do Polars pra tipos Python que ele não mapeia
    nativamente (ex.: `uuid.UUID` de uma coluna UUID do MariaDB, retornado
    assim pelo driver). `pl.List` é o dtype de uma coluna `ARRAY` do Postgres
    (ex.: `text[]`, `integer[]`). Nos dois dtypes, `min()`/`max()` levantam
    `InvalidOperationError` (`n_unique()`/`value_counts()` funcionam
    normalmente, só min/max quebram). Como o domínio já guarda `minimo`/
    `maximo` como `str` (MetricasBaseColuna), convertê-los aqui via `str()`
    não perde nada que seria usado depois, e restaura as mesmas operações
    que qualquer coluna Utf8 já suporta.

    Args:
        serie: valores amostrados da coluna, com dtype Object ou List.

    Returns:
        A mesma série, com valores convertidos para Utf8 (nulos preservados)
        — via `_representar_valor_nao_nativo`, não `str()` puro.
    """
    valores = [_representar_valor_nao_nativo(valor) for valor in serie.to_list()]
    return pl.Series(serie.name, valores, dtype=pl.Utf8)


def _representar_valor_nao_nativo(valor: object) -> str | None:
    """Converte um valor de dtype Object ou List para texto legível.

    `str()` puro é enganoso pra dado binário: `psycopg2` devolve `memoryview`
    pra colunas `bytea`, e `str(memoryview(...))` produz algo como
    `<memory at 0x7f...>` — um endereço de memória, não informação sobre o
    dado. `bytes`/`bytearray`/`memoryview` viram `[dado binário, N bytes]`
    (mesmo espírito do "[binary data]" que o pgAdmin já mostra); qualquer
    outro tipo (ex.: `uuid.UUID`, ou uma `list` vinda de coluna `ARRAY`) usa
    `str()`, que já produz texto útil.

    Args:
        valor: valor bruto de uma célula, ou None.

    Returns:
        Representação textual do valor, ou None se `valor` for None.
    """
    if valor is None:
        return None
    if isinstance(valor, bytes | bytearray | memoryview):
        return f"[dado binário, {len(valor)} bytes]"
    return str(valor)


def _top_valores_frequentes(nao_nulos: pl.Series) -> list[tuple[str, int]]:
    """Top 10 valores não-nulos por frequência, desempatados por valor.

    Args:
        nao_nulos: valores da coluna já sem nulos.

    Returns:
        Até 10 pares (valor, contagem), ordenados por contagem decrescente
        e, em caso de empate, por valor crescente — desempate determinístico
        que `value_counts()` sozinho não garante.
    """
    if nao_nulos.len() == 0:
        return []

    nome = nao_nulos.name
    contagens = nao_nulos.value_counts()
    topo = contagens.sort(by=["count", nome], descending=[True, False]).head(10)
    valores = topo[nome].cast(pl.Utf8).to_list()
    frequencias = topo["count"].to_list()
    return list(zip(valores, frequencias))

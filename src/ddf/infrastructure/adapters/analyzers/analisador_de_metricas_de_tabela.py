"""AnalisadorDeMetricasDeTabela: completude e confiança a partir das colunas."""

import math

from ddf.domain.model.analysis import (
    ContextoDeAnalise,
    MetricasBaseColuna,
    MetricasBaseTabela,
    MetricasDeConfianca,
    NivelDeConfianca,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso

_MARGEM_MAXIMA_ALTA_PP = 5.0
_MARGEM_MAXIMA_MEDIA_PP = 15.0
_Z_95 = 1.96


class AnalisadorDeMetricasDeTabela:
    """Calcula a completude e a confiança de cada tabela a partir das colunas."""

    produz: list[TipoDeMetrica] = [MetricasBaseTabela, MetricasDeConfianca]
    requer: list[TipoDeMetrica] = [MetricasBaseColuna]

    def __call__(self, entrada: ContextoDeAnalise, /) -> Resultado[ContextoDeAnalise]:
        """Acrescenta MetricasBaseTabela e MetricasDeConfianca a cada TabelaAnalisada.

        Args:
            entrada: contexto cujo BancoAnalisado já tem MetricasBaseColuna
                calculada pelo AnalisadorDeMetricasDeColuna em cada coluna.
                Não é modificado — o Analisador é sequencial hoje, mas
                devolve um contexto novo para não impor essa suposição a
                quem o chama (ver docs/system_design_doc.md, Decisão 11).

        Returns:
            Sucesso com um ContextoDeAnalise novo, `analisado` enriquecido
            com MetricasBaseTabela e MetricasDeConfianca por tabela. Falha
            se MetricasBaseColuna estiver ausente ou duplicada em qualquer
            coluna.
        """
        novas_tabelas: list[TabelaAnalisada] = []
        for tabela in entrada.analisado.tabelas:
            resultado_completude = _completude_da_tabela(tabela)
            if isinstance(resultado_completude, Falha):
                return resultado_completude
            nivel = _nivel_de_confianca(
                tamanho_amostra=tabela.metadados_amostra.tamanho_amostra,
                total_linhas=tabela.total_linhas,
            )
            novas_tabelas.append(
                tabela.model_copy(
                    update={
                        "metricas": [
                            *tabela.metricas,
                            MetricasBaseTabela(completude=resultado_completude.valor),
                            MetricasDeConfianca(nivel=nivel),
                        ]
                    }
                )
            )

        novo_contexto = entrada.model_copy(
            update={
                "analisado": entrada.analisado.model_copy(
                    update={"tabelas": novas_tabelas}
                )
            }
        )
        return Sucesso(novo_contexto)


def _completude_da_tabela(tabela: TabelaAnalisada) -> Resultado[float]:
    """Calcula a completude de uma tabela como média de (100 - percentual_nulo).

    Args:
        tabela: tabela analisada cujas colunas já devem ter exatamente uma
            MetricasBaseColuna em `metricas`.

    Returns:
        Sucesso com a completude (0.0 se a tabela não tiver colunas). Falha
        se alguma coluna não tiver MetricasBaseColuna, ou tiver mais de uma.
    """
    if not tabela.colunas:
        return Sucesso(0.0)

    completudes: list[float] = []
    for coluna in tabela.colunas:
        metricas_de_coluna = [
            metrica
            for metrica in coluna.metricas
            if isinstance(metrica, MetricasBaseColuna)
        ]
        if len(metricas_de_coluna) == 0:
            return Falha(
                "MetricasBaseColuna ausente em "
                f"'{tabela.nome_escopo}.{tabela.nome_tabela}.{coluna.nome}': "
                "AnalisadorDeMetricasDeTabela requer que "
                "AnalisadorDeMetricasDeColuna já tenha rodado."
            )
        if len(metricas_de_coluna) > 1:
            return Falha(
                "MetricasBaseColuna duplicada em "
                f"'{tabela.nome_escopo}.{tabela.nome_tabela}.{coluna.nome}': "
                f"{len(metricas_de_coluna)} ocorrências encontradas."
            )
        completudes.append(100 - metricas_de_coluna[0].percentual_nulo)

    return Sucesso(sum(completudes) / len(completudes))


def _nivel_de_confianca(tamanho_amostra: int, total_linhas: int) -> NivelDeConfianca:
    """Classifica a confiança estatística da amostra via margem de erro conservadora.

    Erro-padrão com `p=0,5` fixo (variância máxima, não a proporção
    observada — usar o valor observado colapsaria para `SE=0` numa coluna
    PK/UNIQUE, onde `percentual_unico=100%` zera `p(1-p)` para qualquer
    tamanho de amostra) e correção de população finita, a 95% de confiança:
    `SE = sqrt(0.25/n × (N-n)/(N-1))`. `n = N` (amostra igual à população,
    caso de `AmostragemIntegral`/`TabelaInteira`) zera o fator de correção
    e sempre classifica como `ALTA`, sem tratamento especial por estratégia.

    Args:
        tamanho_amostra: linhas efetivamente amostradas (`n`).
        total_linhas: total real de linhas da tabela (`N`).

    Returns:
        `BAIXA` se a amostra ou a tabela forem vazias; `ALTA` se a amostra
        cobrir a tabela inteira; caso contrário, o nível correspondente à
        margem de erro a 95% (`ALTA` até 5pp, `MEDIA` até 15pp, `BAIXA`
        acima disso).
    """
    if tamanho_amostra <= 0 or total_linhas <= 0:
        return NivelDeConfianca.BAIXA
    if tamanho_amostra >= total_linhas:
        return NivelDeConfianca.ALTA

    erro_padrao = math.sqrt(
        0.25 / tamanho_amostra * (total_linhas - tamanho_amostra) / (total_linhas - 1)
    )
    margem_de_erro_pp = _Z_95 * erro_padrao * 100

    if margem_de_erro_pp <= _MARGEM_MAXIMA_ALTA_PP:
        return NivelDeConfianca.ALTA
    if margem_de_erro_pp <= _MARGEM_MAXIMA_MEDIA_PP:
        return NivelDeConfianca.MEDIA
    return NivelDeConfianca.BAIXA

"""AnalisadorDeMetricasDeTabela: completude por tabela a partir das colunas."""

from ddf.domain.model.analysis import (
    ContextoDeAnalise,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


class AnalisadorDeMetricasDeTabela:
    """Calcula a completude de cada tabela a partir das métricas de coluna."""

    produz: list[TipoDeMetrica] = [MetricasBaseTabela]
    requer: list[TipoDeMetrica] = [MetricasBaseColuna]

    def __call__(self, entrada: ContextoDeAnalise, /) -> Resultado[ContextoDeAnalise]:
        """Acrescenta MetricasBaseTabela a cada TabelaAnalisada.

        Args:
            entrada: contexto cujo BancoAnalisado já tem MetricasBaseColuna
                calculada pelo AnalisadorDeMetricasDeColuna em cada coluna.
                Não é modificado — o Analisador é sequencial hoje, mas
                devolve um contexto novo para não impor essa suposição a
                quem o chama (ver docs/system_design_doc.md, Decisão 11).

        Returns:
            Sucesso com um ContextoDeAnalise novo, `analisado` enriquecido
            com MetricasBaseTabela por tabela. Falha se MetricasBaseColuna
            estiver ausente ou duplicada em qualquer coluna.
        """
        novas_tabelas: list[TabelaAnalisada] = []
        for tabela in entrada.analisado.tabelas:
            resultado_completude = _completude_da_tabela(tabela)
            if isinstance(resultado_completude, Falha):
                return resultado_completude
            novas_tabelas.append(
                tabela.model_copy(
                    update={
                        "metricas": [
                            *tabela.metricas,
                            MetricasBaseTabela(completude=resultado_completude.valor),
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

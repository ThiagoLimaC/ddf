"""Helper agnóstico de fonte pra montar MetadadosDeAmostra e os Avisos de custo."""

from typing import assert_never

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
)
from ddf.domain.shared.aviso import Aviso


def construir_metadados_de_amostra(
    nome: str,
    requisicao: RequisicaoDeAmostragem,
    tamanho_amostra: int,
    total_linhas: int,
    origem: str,
    causa_provavel: str,
    identificador_tabela: str,
) -> tuple[MetadadosDeAmostra, list[Aviso]]:
    """Monta MetadadosDeAmostra e emite os Avisos de custo associados à estratégia.

    Dois Avisos independentes, nenhum fatal: (1) toda vez que a requisição é
    AmostragemProbabilistica, documenta que a leitura varre a tabela inteira
    independente do percentual pedido — limitação estrutural da estratégia
    (ver docstring de `PercentualDeLinhas`), não uma condição de erro; (2)
    quando a amostra excede `total_linhas`, sintoma de estimativa de
    catálogo desatualizada. Ambos citam `identificador_tabela`, mesmo padrão
    de `construir_colunas_fk` — sem isso, os exemplos que `avisos.py` mostra
    antes de colapsar por contagem ficam anônimos, sem dizer qual tabela
    específica paga o custo.

    Args:
        nome: identificador da EstrategiaDeAmostragem (MetadadosDeAmostra.estrategia).
        requisicao: o que foi efetivamente pedido ao Extrator — decide se
            `percentual`/`seed` são registrados (AmostragemProbabilistica) ou
            ficam None (AmostragemIntegral, sem política probabilística).
        tamanho_amostra: nº de linhas de fato lidas na amostra.
        total_linhas: estimativa de catálogo da tabela. Em AmostragemIntegral,
            o chamador já passa `len(amostra)` aqui — a divergência abaixo
            nunca dispara nesse caso, por construção (mesmo valor dos dois
            lados), não por um caso especial tratado aqui.
        origem: nome do Extrator concreto, usado em Aviso.origem.
        causa_provavel: explicação, específica do motor, de por que
            total_linhas pode estar desatualizado (ex.: "sem ANALYZE
            recente" no Postgres, "sem ANALYZE TABLE recente" no MariaDB).
        identificador_tabela: "escopo.tabela", citado nas mensagens de Aviso.
    """
    avisos: list[Aviso] = []
    match requisicao:
        case AmostragemProbabilistica(percentual=percentual, seed=seed):
            metadados = MetadadosDeAmostra(
                estrategia=nome,
                tamanho_amostra=tamanho_amostra,
                percentual=percentual,
                seed=seed,
            )
            avisos.append(
                Aviso(
                    mensagem=(
                        f"'{identificador_tabela}': amostragem por percentual "
                        f"faz varredura sequencial completa da tabela "
                        f"({total_linhas} linhas), independente do percentual "
                        "pedido — custo de I/O não escala com o tamanho da "
                        "amostra resultante."
                    ),
                    origem=origem,
                )
            )
        case AmostragemIntegral():
            metadados = MetadadosDeAmostra(
                estrategia=nome, tamanho_amostra=tamanho_amostra
            )
        case _ as nunca:
            assert_never(nunca)

    if tamanho_amostra > total_linhas:
        avisos.append(
            Aviso(
                mensagem=(
                    f"'{identificador_tabela}': amostra ({tamanho_amostra} "
                    f"linhas) maior que total_linhas ({total_linhas}) — "
                    f"total_linhas pode estar desatualizado ({causa_provavel})."
                ),
                origem=origem,
            )
        )
    return metadados, avisos

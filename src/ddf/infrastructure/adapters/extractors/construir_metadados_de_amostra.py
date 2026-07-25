"""Helper agnóstico de fonte pra montar MetadadosDeAmostra e o Aviso de divergência."""

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
) -> tuple[MetadadosDeAmostra, list[Aviso]]:
    """Monta MetadadosDeAmostra e emite Aviso quando a amostra diverge de total_linhas.

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
    """
    match requisicao:
        case AmostragemProbabilistica(percentual=percentual, seed=seed):
            metadados = MetadadosDeAmostra(
                estrategia=nome,
                tamanho_amostra=tamanho_amostra,
                percentual=percentual,
                seed=seed,
            )
        case AmostragemIntegral():
            metadados = MetadadosDeAmostra(
                estrategia=nome, tamanho_amostra=tamanho_amostra
            )
        case _ as nunca:
            assert_never(nunca)

    avisos: list[Aviso] = []
    if tamanho_amostra > total_linhas:
        avisos.append(
            Aviso(
                mensagem=(
                    f"Amostra ({tamanho_amostra} linhas) maior que total_linhas "
                    f"({total_linhas}) — total_linhas pode estar desatualizado "
                    f"({causa_provavel})."
                ),
                origem=origem,
            )
        )
    return metadados, avisos

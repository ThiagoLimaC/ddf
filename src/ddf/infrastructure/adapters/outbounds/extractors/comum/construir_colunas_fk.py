"""Helper agnóstico de fonte pra montar referências de FK a partir de linhas cruas."""

from collections import defaultdict
from collections.abc import Iterable

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna


def construir_colunas_fk(
    linhas_fk: Iterable[tuple[str, str, str, str]],
) -> dict[str, list[ReferenciaDeColuna]]:
    """Monta o dict coluna→referências de FK, agrupando por coluna.

    ColunaExtraida.referencias é uma lista por design — uma coluna pode ter
    2+ constraints FK de coluna única distintas apontando pra tabelas
    diferentes (FK polimórfica sem discriminator). Nenhuma referência é
    descartada: todas as linhas de uma coluna viram uma entrada na lista,
    na ordem em que chegam (a query do Extrator concreto já ordena por
    constraint_name, garantindo ordem determinística entre execuções).

    Args:
        linhas_fk: linhas cruas (nome_coluna, escopo_referenciado,
            tabela_referenciada, coluna_referenciada) retornadas pela query
            de FK do Extrator concreto.

    Returns:
        Dict coluna → lista de referências, na ordem de chegada das linhas.
        Coluna sem nenhuma FK simplesmente não aparece no dict.
    """
    colunas_fk: dict[str, list[ReferenciaDeColuna]] = defaultdict(list)
    for (
        nome_coluna_fk,
        escopo_referenciado,
        tabela_referenciada,
        coluna_referenciada,
    ) in linhas_fk:
        colunas_fk[nome_coluna_fk].append(
            ReferenciaDeColuna(
                nome_escopo=escopo_referenciado,
                nome_tabela=tabela_referenciada,
                nome_coluna=coluna_referenciada,
            )
        )
    return dict(colunas_fk)

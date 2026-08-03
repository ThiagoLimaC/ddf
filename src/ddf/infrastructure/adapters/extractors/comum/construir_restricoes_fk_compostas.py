"""Helper agnóstico de fonte pra agrupar linhas de FK por constraint composta."""

from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple

from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta


class _LinhaFk(NamedTuple):
    """Uma linha de FK crua, nomeada por campo."""

    coluna_local: str
    escopo_referenciado: str
    tabela_referenciada: str
    coluna_referenciada: str
    constraint_name: str


def construir_restricoes_fk_compostas(
    linhas_fk: Iterable[tuple[str, str, str, str, str]],
) -> list[RestricaoDeFkComposta]:
    """Agrupa linhas de FK de uma tabela por constraint, isolando as compostas.

    Espelha `construir_colunas_fk` (mesmo padrão de helper agnóstico de
    fonte), mas em vez de resolver as referências por coluna, agrupa as
    linhas que pertencem à mesma constraint — uma FK de coluna única
    continua representada só por `ColunaExtraida.referencias`; este helper
    só produz `RestricaoDeFkComposta` para grupos de 2+ colunas.

    Args:
        linhas_fk: linhas cruas de uma única tabela (nome_coluna_local,
            escopo_referenciado, tabela_referenciada, coluna_referenciada,
            constraint_name), já ordenadas por posição dentro da
            constraint pela query do Extrator concreto — a ordem de
            iteração determina a ordem de `colunas_locais`/
            `colunas_referenciadas` no Value Object resultante.

    Returns:
        Uma `RestricaoDeFkComposta` por constraint que agrupa 2+ colunas;
        constraints de coluna única não aparecem aqui.
    """
    grupos: dict[str, list[_LinhaFk]] = defaultdict(list)
    for linha_crua in linhas_fk:
        linha = _LinhaFk(*linha_crua)
        grupos[linha.constraint_name].append(linha)

    restricoes: list[RestricaoDeFkComposta] = []
    for linhas_da_constraint in grupos.values():
        if len(linhas_da_constraint) < 2:
            continue
        colunas_locais: list[str] = []
        colunas_referenciadas: list[str] = []
        for linha in linhas_da_constraint:
            colunas_locais.append(linha.coluna_local)
            colunas_referenciadas.append(linha.coluna_referenciada)
        primeira = linhas_da_constraint[0]
        restricoes.append(
            RestricaoDeFkComposta(
                colunas_locais=tuple(colunas_locais),
                nome_escopo_referenciado=primeira.escopo_referenciado,
                nome_tabela_referenciada=primeira.tabela_referenciada,
                colunas_referenciadas=tuple(colunas_referenciadas),
            )
        )
    return restricoes

"""Heurísticas de sugestão de teste dbt por coluna, e detecção de macro órfão.

Os predicados "existe consumidor real deste artefato opcional nesta
execução" (`_precisa_matches_format`, `_precisa_unique_percentage_at_least`,
`_precisa_dbt_utils`, `_precisa_composite_relationships`) ficam neste mesmo
módulo, não em um módulo separado — são derivações diretas dos mesmos
predicados de teste "soft" (`_precisa_teste_soft_nulo`/
`_precisa_teste_soft_unico`) definidos aqui. Separá-los criaria import
cruzado e forçaria editar dois arquivos toda vez que um threshold soft
mudasse — mesma razão de mudança, um módulo só.
"""

from typing import Any

from ddf.domain.model.analysis import (
    ColunaAnalisada,
    MetricasBaseColuna,
    TabelaAnalisada,
)
from ddf.domain.shared.aviso import Aviso
from ddf.infrastructure.adapters.generators.comum._metricas import (
    _elegivel_para_enumeracao,
    _metrica_de_coluna,
)
from ddf.infrastructure.adapters.generators.dbt._sql import _nome_model

_ORIGEM = "GeradorDbt"

# Testes "soft" — thresholds fixos, não configuráveis nesta v1.
# Mais afastados da fronteira (10%/95%, não 5%/90%) de propósito: perto do
# piso de amostra (_TAMANHO_AMOSTRA_MINIMO_SOFT), o erro padrão de uma
# proporção é da mesma ordem de um threshold mais apertado — a sugestão
# "piscaria" entre reextrações por ruído amostral, não mudança real de dado.
_LIMITE_NULO_SOFT = 10.0
_LIMITE_UNICO_SOFT = 95.0
_TAMANHO_AMOSTRA_MINIMO_SOFT = 100


def _precisa_teste_soft_nulo(
    coluna: ColunaAnalisada, metrica: MetricasBaseColuna | None, tamanho_amostra: int
) -> bool:
    """Decide se a coluna cai na faixa "nulo baixo mas não-zero".

    Mutuamente exclusivo com o `not_null` hard por construção: hard cobre
    `percentual_nulo == 0.0` ou `coluna.nao_nulavel`; aqui a faixa exige
    `percentual_nulo > 0` e a coluna não ser estruturalmente not-nullable.

    Args:
        coluna: coluna analisada a avaliar.
        metrica: MetricasBaseColuna da coluna, se já calculada.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        True se o teste soft de nulo deve ser sugerido.
    """
    if coluna.chave_primaria or coluna.nao_nulavel:
        return False
    if metrica is None or tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_SOFT:
        return False
    return 0 < metrica.percentual_nulo <= _LIMITE_NULO_SOFT


def _precisa_teste_soft_unico(
    coluna: ColunaAnalisada, metrica: MetricasBaseColuna | None, tamanho_amostra: int
) -> bool:
    """Decide se a coluna cai na faixa "quase única".

    Mutuamente exclusivo com o `unique` hard por construção: hard cobre
    `percentual_unico == 100.0` ou `coluna.unica`; aqui a faixa exige
    `percentual_unico < 100.0` e a coluna não ser estruturalmente única.

    Args:
        coluna: coluna analisada a avaliar.
        metrica: MetricasBaseColuna da coluna, se já calculada.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        True se o teste soft de unicidade deve ser sugerido.
    """
    if coluna.chave_primaria or coluna.unica:
        return False
    if metrica is None or tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_SOFT:
        return False
    return _LIMITE_UNICO_SOFT <= metrica.percentual_unico < 100.0


def _sugestoes_de_teste(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
    tamanho_amostra: int,
    colunas_em_fk_composta: set[str],
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis a uma coluna.

    `unique`/`not_null` combinam o fato estrutural do schema com a métrica
    amostral, priorizando sempre o fato do schema; suprimidos se a coluna
    já é PK. `relationships` só é sugerido se a coluna tem exatamente 1
    referência **e** a tabela referenciada está no lote analisado — senão
    emite `Aviso` e omite o teste. Coluna com 2+ referências (FK
    polimórfica sem discriminator) nunca recebe `relationships`
    automático — o teste assumiria "toda linha satisfaz a relação A",
    falso positivo garantido quando a linha na verdade satisfaz a relação
    B; emite `Aviso` explicando a ambiguidade em vez de testar. Coluna em
    `colunas_em_fk_composta` nunca recebe `relationships` per-coluna, esse
    teste vai para `_testes_de_modelo` (`composite_relationships`).
    `accepted_values` exige `_elegivel_para_enumeracao` (critérios em
    `_metricas.py`). `matches_format` exige `formato_detectado`. Testes
    "soft" de nulo/unicidade cobrem a faixa intermediária entre "sem sinal"
    e o `not_null`/`unique` hard (condições em
    `_precisa_teste_soft_nulo`/`_precisa_teste_soft_unico`).

    Critérios e thresholds detalhados: `docs/low_level_design.md`, seção
    `GeradorDbt`.

    Args:
        coluna: coluna analisada a avaliar.
        presentes: pares (nome_escopo, nome_tabela) de todas as tabelas do
            lote analisado nesta execução.
        avisos: lista de avisos acumulada pelo Gerador, alimentada quando
            uma FK referencia tabela fora do lote.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        colunas_em_fk_composta: nomes de coluna desta tabela que pertencem
            a alguma `RestricaoDeFkComposta` — suprime `relationships`
            per-coluna pra elas.

    Returns:
        Lista de testes no formato aceito por `schema.yml` (strings para
        testes sem argumento, dicts para `relationships`/`accepted_values`).
    """
    testes: list[Any] = []
    metrica = _metrica_de_coluna(coluna)

    unico = coluna.unica or (
        tamanho_amostra > 0
        and metrica is not None
        and metrica.percentual_unico == 100.0
    )
    nao_nulo = coluna.nao_nulavel or (
        tamanho_amostra > 0 and metrica is not None and metrica.percentual_nulo == 0.0
    )
    if unico and not coluna.chave_primaria:
        testes.append("unique")
    if nao_nulo and not coluna.chave_primaria:
        testes.append("not_null")

    if metrica is not None and metrica.formato_detectado is not None:
        testes.append(
            {
                "matches_format": {
                    "format": metrica.formato_detectado,
                    "config": {"severity": "warn"},
                }
            }
        )

    if _precisa_teste_soft_nulo(coluna, metrica, tamanho_amostra):
        testes.append(
            {
                "dbt_utils.not_null_proportion": {
                    "at_least": round(1 - _LIMITE_NULO_SOFT / 100, 4),
                    "config": {"severity": "warn"},
                }
            }
        )
    if _precisa_teste_soft_unico(coluna, metrica, tamanho_amostra):
        testes.append(
            {
                "unique_percentage_at_least": {
                    "at_least": round(_LIMITE_UNICO_SOFT / 100, 4),
                    "config": {"severity": "warn"},
                }
            }
        )

    if (
        coluna.chave_estrangeira
        and len(coluna.referencias) > 1
        and coluna.nome not in colunas_em_fk_composta
    ):
        tabelas = ", ".join(
            f"{referencia.nome_escopo}.{referencia.nome_tabela}"
            for referencia in coluna.referencias
        )
        alvos = ", ".join(
            f"'{referencia.nome_escopo}.{referencia.nome_tabela}."
            f"{referencia.nome_coluna}'"
            for referencia in coluna.referencias
        )
        avisos.append(
            Aviso(
                mensagem=(
                    f"Coluna '{coluna.nome}' pode se referir a mais de uma tabela "
                    f"({tabelas}) — o ddf não sabe qual delas testar "
                    "automaticamente, então nenhum teste relationships foi gerado "
                    f"para essa coluna. Detalhe técnico: {len(coluna.referencias)} "
                    f"FKs distintas ({alvos}), FK polimórfica sem discriminator. "
                    "Se quiser validar cada relação, adicione um teste manual com "
                    "`where` filtrando por uma coluna que diga o tipo de cada "
                    "linha (discriminator)."
                ),
                origem=_ORIGEM,
            )
        )
    elif (
        coluna.chave_estrangeira
        and len(coluna.referencias) == 1
        and coluna.nome not in colunas_em_fk_composta
    ):
        referencia = coluna.referencias[0]
        if (referencia.nome_escopo, referencia.nome_tabela) in presentes:
            nome_model_referenciado = _nome_model(
                referencia.nome_escopo, referencia.nome_tabela
            )
            testes.append(
                {
                    "relationships": {
                        "to": f"ref('{nome_model_referenciado}')",
                        "field": referencia.nome_coluna,
                    }
                }
            )
        else:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"Coluna '{coluna.nome}' referencia "
                        f"'{referencia.nome_escopo}.{referencia.nome_tabela}', fora "
                        "do lote analisado nesta execução — teste relationships "
                        "omitido."
                    ),
                    origem=_ORIGEM,
                )
            )

    elegivel = _elegivel_para_enumeracao(coluna, metrica, tamanho_amostra)
    if elegivel and metrica is not None:
        testes.append(
            {
                "accepted_values": {
                    "values": [valor for valor, _ in metrica.valores_frequentes],
                    "config": {"severity": "warn"},
                }
            }
        )

    return testes


def _precisa_matches_format(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se algum consumidor real de `macros/matches_format/` existe no lote.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se pelo menos uma coluna tem `formato_detectado` calculado —
        escrever os macros sem isso seria decoração no artefato gerado.
    """
    for tabela in tabelas:
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if metrica is not None and metrica.formato_detectado is not None:
                return True
    return False


def _precisa_unique_percentage_at_least(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se algum consumidor de `unique_percentage_at_least.sql` existe no lote.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se pelo menos uma coluna cai na faixa "soft" de unicidade (ver
        `_precisa_teste_soft_unico`).
    """
    for tabela in tabelas:
        tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if _precisa_teste_soft_unico(coluna, metrica, tamanho_amostra):
                return True
    return False


def _precisa_dbt_utils(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se `packages.yml` (dependência `dbt_utils`) precisa ser escrito.

    Dois consumidores reais possíveis: `dbt_utils.unique_combination_of_columns`
    (UNIQUE composto) e `dbt_utils.not_null_proportion` (teste soft de nulo)
    — sem nenhum dos dois, declarar a dependência seria decoração no
    artefato gerado.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se houver ao menos um consumidor real de `dbt_utils` no lote.
    """
    if any(tabela.restricoes_unicas for tabela in tabelas):
        return True
    for tabela in tabelas:
        tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if _precisa_teste_soft_nulo(coluna, metrica, tamanho_amostra):
                return True
    return False


def _precisa_composite_relationships(
    tabelas: list[TabelaAnalisada], presentes: set[tuple[str, str]]
) -> bool:
    """Indica se algum consumidor real de `macros/composite_relationships.sql` existe.

    Args:
        tabelas: tabelas do lote analisado.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.

    Returns:
        True se pelo menos uma `RestricaoDeFkComposta` referencia uma
        tabela presente no lote — sem isso, `_testes_de_modelo` só emite
        `Aviso` (fora do lote) e nunca gera o teste, então escrever o macro
        seria decoração no artefato gerado.
    """
    for tabela in tabelas:
        for restricao in tabela.restricoes_fk_compostas:
            chave_referenciada = (
                restricao.nome_escopo_referenciado,
                restricao.nome_tabela_referenciada,
            )
            if chave_referenciada in presentes:
                return True
    return False

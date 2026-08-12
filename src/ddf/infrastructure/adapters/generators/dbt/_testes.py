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

from dataclasses import dataclass
from typing import Any

from ddf.domain.model.analysis import (
    ColunaAnalisada,
    MetricasBaseColuna,
    TabelaAnalisada,
)
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.infrastructure.adapters.generators.comum._metricas import (
    _elegivel_para_enumeracao,
    _metrica_de_coluna,
)
from ddf.infrastructure.adapters.generators.dbt._sql import _nome_model


@dataclass
class ContadoresDeAviso:
    """Contagem de ocorrências de cada categoria de Aviso do GeradorDbt.

    Substitui um `Aviso` por ocorrência (uma FK composta/polimórfica/fora
    do lote por linha) por uma contagem — `GeradorDbt.__call__` agrega
    cada categoria num único `Aviso` ao final, mesmo padrão de
    `GeradorMarkdown`/`AnalisadorDeMetricasDeColuna`: um schema real com
    muitas FKs assim geraria dezenas de avisos soltos, um por coluna.
    """

    fk_composta_fora_do_lote: int = 0
    fk_polimorfica: int = 0
    fk_fora_do_lote: int = 0


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


def _referencias_de_fk_composta(
    nome_coluna: str, restricoes_fk_compostas: list[RestricaoDeFkComposta]
) -> set[tuple[str, str, str]]:
    """Referências (escopo, tabela, coluna) que `nome_coluna` cobre via FK composta.

    `construir_colunas_fk` não descarta a decomposição por coluna de uma FK
    composta — `ColunaAnalisada.referencias` acaba com uma entrada por
    constraint composta da qual a coluna participa, além de qualquer FK
    single-column legítima que ela também tenha. Esta função identifica só
    as entradas de origem composta, pareando por posição
    (`colunas_locais[i]` ↔ `colunas_referenciadas[i]`), para que
    `_sugestoes_de_teste` possa excluí-las sem descartar uma referência
    própria genuína da mesma coluna.

    Args:
        nome_coluna: nome da coluna analisada.
        restricoes_fk_compostas: `RestricaoDeFkComposta` da tabela desta
            coluna.

    Returns:
        Conjunto de tuplas (nome_escopo, nome_tabela, nome_coluna) — vazio
        se `nome_coluna` não participa de nenhuma FK composta.
    """
    referencias: set[tuple[str, str, str]] = set()
    for restricao in restricoes_fk_compostas:
        if nome_coluna not in restricao.colunas_locais:
            continue
        indice = restricao.colunas_locais.index(nome_coluna)
        referencias.add(
            (
                restricao.nome_escopo_referenciado,
                restricao.nome_tabela_referenciada,
                restricao.colunas_referenciadas[indice],
            )
        )
    return referencias


def _sugestoes_de_teste(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    contadores: ContadoresDeAviso,
    tamanho_amostra: int,
    restricoes_fk_compostas: list[RestricaoDeFkComposta],
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis a uma coluna.

    `unique`/`not_null` priorizam sempre o fato estrutural do schema
    (`severity: error`, o padrão do dbt); na ausência dele, caem para o
    ramo amostral só acima do piso `_TAMANHO_AMOSTRA_MINIMO_SOFT`, com
    `severity: warn` — mesma política dos demais testes soft, evita que uma
    amostra pequena declare "100% único"/"0% nulo" com a mesma confiança de
    um fato de schema real. Suprimidos se a coluna já é PK. `relationships`
    só é sugerido se a coluna tem exatamente 1
    referência **própria** (fora de qualquer FK composta, ver
    `_referencias_de_fk_composta`) **e** a tabela referenciada está no
    lote analisado — senão emite `Aviso` e omite o teste. Coluna com 2+
    referências próprias (FK polimórfica sem discriminator) nunca recebe
    `relationships` automático — o teste assumiria "toda linha satisfaz a
    relação A", falso positivo garantido quando a linha na verdade
    satisfaz a relação B; emite `Aviso` explicando a ambiguidade em vez de
    testar. A(s) referência(s) que uma coluna tem só por participar de uma
    FK composta nunca vira `relationships` per-coluna nem entra na conta
    de polimorfismo — esse teste vai para `_testes_de_modelo`
    (`composite_relationships`); se, depois de filtradas, não sobra
    nenhuma referência própria, nada foi de fato suprimido e nenhum
    `Aviso` é emitido.
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
        contadores: contadores de Aviso acumulados pelo Gerador, incrementados
            quando uma FK é polimórfica ou referencia tabela fora do lote.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        restricoes_fk_compostas: `RestricaoDeFkComposta` da tabela desta
            coluna — usado só para filtrar de `coluna.referencias` as
            entradas que já são cobertas por `composite_relationships`
            (ver `_referencias_de_fk_composta`), sem descartar uma
            referência single-column própria que a mesma coluna também
            tenha.

    Returns:
        Lista de testes no formato aceito por `schema.yml` (strings para
        testes sem argumento, dicts para `relationships`/`accepted_values`).
    """
    testes: list[Any] = []
    metrica = _metrica_de_coluna(coluna)

    if not coluna.chave_primaria:
        if coluna.unica:
            testes.append("unique")
        elif (
            metrica is not None
            and metrica.percentual_unico == 100.0
            and tamanho_amostra >= _TAMANHO_AMOSTRA_MINIMO_SOFT
        ):
            testes.append({"unique": {"config": {"severity": "warn"}}})

        if coluna.nao_nulavel:
            testes.append("not_null")
        elif (
            metrica is not None
            and metrica.percentual_nulo == 0.0
            and tamanho_amostra >= _TAMANHO_AMOSTRA_MINIMO_SOFT
        ):
            testes.append({"not_null": {"config": {"severity": "warn"}}})

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

    referencias_compostas = _referencias_de_fk_composta(
        coluna.nome, restricoes_fk_compostas
    )
    referencias_proprias = [
        referencia
        for referencia in coluna.referencias
        if (referencia.nome_escopo, referencia.nome_tabela, referencia.nome_coluna)
        not in referencias_compostas
    ]

    if len(referencias_proprias) > 1:
        contadores.fk_polimorfica += 1
    elif len(referencias_proprias) == 1:
        referencia = referencias_proprias[0]
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
            contadores.fk_fora_do_lote += 1

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

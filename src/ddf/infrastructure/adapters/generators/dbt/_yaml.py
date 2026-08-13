"""Montagem de `schema.yml`, `sources.yml` e README.md do projeto dbt gerado."""

from typing import Any

import yaml

from ddf.domain.model.analysis import ColunaAnalisada, TabelaAnalisada
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.infrastructure.adapters.generators.comum._metricas import (
    _metrica_de_confianca,
)
from ddf.infrastructure.adapters.generators.dbt._sql import _nome_model
from ddf.infrastructure.adapters.generators.dbt._templates import _TEMPLATE_README
from ddf.infrastructure.adapters.generators.dbt._testes import (
    ContadoresDeAviso,
    _sugestoes_de_teste,
)


def _coluna_schema_yaml(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    contadores: ContadoresDeAviso,
    tamanho_amostra: int,
    restricoes_fk_compostas: list[RestricaoDeFkComposta],
) -> dict[str, Any]:
    """Monta a entrada de uma coluna em `schema.yml`.

    Args:
        coluna: coluna analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        contadores: contadores de Aviso acumulados pelo Gerador.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        restricoes_fk_compostas: `RestricaoDeFkComposta` da tabela desta
            coluna — usado por `_sugestoes_de_teste` pra não suprimir uma
            referência single-column própria só porque a coluna também
            participa de uma FK composta (ver `_referencias_de_fk_composta`).

    Returns:
        Dict com `name`, `description` opcional (de `papel_de_negocio`) e
        `tests` opcional (omitido quando nenhuma regra se aplica).
    """
    entrada: dict[str, Any] = {"name": coluna.nome}
    if coluna.papel_de_negocio:
        entrada["description"] = coluna.papel_de_negocio
    testes = _sugestoes_de_teste(
        coluna, presentes, contadores, tamanho_amostra, restricoes_fk_compostas
    )
    if testes:
        entrada["tests"] = testes
    return entrada


def _testes_de_modelo(
    tabela: TabelaAnalisada,
    presentes: set[tuple[str, str]],
    contadores: ContadoresDeAviso,
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis no nível do model (tabela).

    Diferente de `_sugestoes_de_teste` (nível coluna), dois testes vivem
    aqui, ambos com severidade padrão (`error`):

    - `dbt_utils.unique_combination_of_columns` — um por `RestricaoUnica`
      (UNIQUE composto real do schema).
    - `composite_relationships` — um por `RestricaoDeFkComposta`, só quando
      a tabela referenciada está no lote (mesma regra do `relationships`
      single-column); senão, incrementa `contadores` e omite o teste.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado —
            usado só pela checagem de `composite_relationships`.
        contadores: contadores de Aviso acumulados pelo Gerador, alimentados
            quando uma FK composta referencia tabela fora do lote.

    Returns:
        Lista de testes no formato aceito por `schema.yml` (dicts).
    """
    testes: list[Any] = [
        {
            "dbt_utils.unique_combination_of_columns": {
                "combination_of_columns": list(restricao.colunas),
            }
        }
        for restricao in tabela.restricoes_unicas
    ]
    for restricao_fk in tabela.restricoes_fk_compostas:
        chave_referenciada = (
            restricao_fk.nome_escopo_referenciado,
            restricao_fk.nome_tabela_referenciada,
        )
        if chave_referenciada not in presentes:
            contadores.fk_composta_fora_do_lote += 1
            continue
        nome_model_referenciado = _nome_model(*chave_referenciada)
        testes.append(
            {
                "composite_relationships": {
                    "column_names": list(restricao_fk.colunas_locais),
                    "to": f"ref('{nome_model_referenciado}')",
                    "field_names": list(restricao_fk.colunas_referenciadas),
                }
            }
        )
    return testes


def _model_schema_yaml(
    tabela: TabelaAnalisada,
    presentes: set[tuple[str, str]],
    contadores: ContadoresDeAviso,
) -> dict[str, Any]:
    """Monta a entrada de um staging model em `schema.yml`.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        contadores: contadores de Aviso acumulados pelo Gerador.

    Returns:
        Dict com `name`, `description` opcional, `tests` opcional
        (model-level, ver `_testes_de_modelo`), `meta.confianca_estatistica`
        opcional (anotação informativa — nunca altera `severity` de nenhum
        teste sugerido, ver `MetricasDeConfianca`) e a lista de `columns`.
    """
    nome_model = _nome_model(tabela.nome_escopo, tabela.nome_tabela)
    entrada: dict[str, Any] = {"name": nome_model}
    if tabela.papel_de_negocio:
        entrada["description"] = tabela.papel_de_negocio
    testes_de_modelo = _testes_de_modelo(tabela, presentes, contadores)
    if testes_de_modelo:
        entrada["tests"] = testes_de_modelo
    metrica_confianca = _metrica_de_confianca(tabela)
    if metrica_confianca is not None:
        entrada["meta"] = {"confianca_estatistica": metrica_confianca.nivel.value}
    tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
    entrada["columns"] = [
        _coluna_schema_yaml(
            coluna,
            presentes,
            contadores,
            tamanho_amostra,
            tabela.restricoes_fk_compostas,
        )
        for coluna in tabela.colunas
    ]
    return entrada


def _agrupar_por_escopo(
    tabelas: list[TabelaAnalisada],
) -> dict[str, list[TabelaAnalisada]]:
    """Agrupa tabelas por escopo, preservando a ordem de primeira aparição.

    Única fonte de agrupamento por escopo do Gerador — `GeradorDbt.__call__`,
    `_montar_sources` e `_renderizar_readme` reaproveitam este resultado em
    vez de reagrupar cada um por conta própria.

    Args:
        tabelas: tabelas do lote analisado, já ordenadas por
            `(nome_escopo, nome_tabela)`.

    Returns:
        Dict `{escopo: [TabelaAnalisada, ...]}`.
    """
    tabelas_por_escopo: dict[str, list[TabelaAnalisada]] = {}
    for tabela in tabelas:
        tabelas_por_escopo.setdefault(tabela.nome_escopo, []).append(tabela)
    return tabelas_por_escopo


def _montar_sources(
    escopo: str, tabelas_do_escopo: list[TabelaAnalisada]
) -> dict[str, Any]:
    """Monta o `sources.yml` de um único escopo.

    Args:
        escopo: nome do escopo — todas as tabelas em `tabelas_do_escopo`
            pertencem a ele.
        tabelas_do_escopo: tabelas desse escopo.

    Returns:
        Dict `{"version": 2, "sources": [{"name": escopo, "tables": [...]}]}`.
    """
    return {
        "version": 2,
        "sources": [
            {
                "name": escopo,
                "tables": [
                    {"name": tabela.nome_tabela} for tabela in tabelas_do_escopo
                ],
            }
        ],
    }


def _renderizar_readme(
    tabelas_por_escopo: dict[str, list[TabelaAnalisada]],
    gerado_em: str,
    usa_dbt_utils: bool,
    usa_matches_format: bool,
    usa_bigint: bool,
) -> str:
    """Renderiza o README.md do projeto dbt gerado, na raiz do projeto.

    Args:
        tabelas_por_escopo: tabelas do lote, já agrupadas por escopo
            (`_agrupar_por_escopo`).
        gerado_em: timestamp ISO 8601 da execução, compartilhado com
            `dbt_project.yml`.
        usa_dbt_utils: se `packages.yml` foi gerado nesta execução — o bloco
            de comandos só menciona `dbt deps` quando há dependência real
            a instalar.
        usa_matches_format: se `macros/matches_format/` foi gerado nesta
            execução — a nota sobre engines suportadas (Postgres/MariaDB
            nesta v1) só aparece quando há consumidor real.
        usa_bigint: se há coluna BIGINT no lote — aciona a nota sobre
            `BIGINT UNSIGNED` virar negativo em silêncio quando o destino
            é MariaDB (limitação conhecida, ver
            `plan/registry-plan/fase-9-fechamento-da-v1/issue-140-*.md`).

    Returns:
        Markdown listando os escopos e tabelas cobertos, com o caminho real
        de cada staging model — calculado via `_nome_model`, nunca
        remontado à parte no template, pra não divergir se a convenção de
        nome do model mudar.
    """
    escopos = [
        {
            "nome": escopo,
            "tabelas": [
                {
                    "nome": tabela.nome_tabela,
                    "caminho_sql": (
                        f"models/staging/{escopo}/"
                        f"{_nome_model(escopo, tabela.nome_tabela)}.sql"
                    ),
                }
                for tabela in tabelas
            ],
        }
        for escopo, tabelas in tabelas_por_escopo.items()
    ]
    return _TEMPLATE_README.render(
        escopos=escopos,
        gerado_em=gerado_em,
        usa_dbt_utils=usa_dbt_utils,
        usa_matches_format=usa_matches_format,
        usa_bigint=usa_bigint,
    )


def _dump_yaml(conteudo: dict[str, Any]) -> str:
    """Serializa um dict em YAML determinístico (ordem preservada, unicode)."""
    return yaml.safe_dump(conteudo, sort_keys=False, allow_unicode=True)

"""Montagem de `schema.yml`, `sources.yml` e README.md do projeto dbt gerado."""

from typing import Any

import yaml

from ddf.domain.model.analysis import ColunaAnalisada, TabelaAnalisada
from ddf.domain.shared.aviso import Aviso
from ddf.infrastructure.adapters.generators.dbt._sql import _nome_model
from ddf.infrastructure.adapters.generators.dbt._templates import _TEMPLATE_README
from ddf.infrastructure.adapters.generators.dbt._testes import _sugestoes_de_teste

_ORIGEM = "GeradorDbt"


def _coluna_schema_yaml(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
    tamanho_amostra: int,
    colunas_em_fk_composta: set[str],
) -> dict[str, Any]:
    """Monta a entrada de uma coluna em `schema.yml`.

    Args:
        coluna: coluna analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        avisos: lista de avisos acumulada pelo Gerador.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        colunas_em_fk_composta: nomes de coluna desta tabela que pertencem
            a alguma `RestricaoDeFkComposta` (issue #95).

    Returns:
        Dict com `name`, `description` opcional (de `papel_de_negocio`) e
        `tests` opcional (omitido quando nenhuma regra se aplica).
    """
    entrada: dict[str, Any] = {"name": coluna.nome}
    if coluna.papel_de_negocio:
        entrada["description"] = coluna.papel_de_negocio
    testes = _sugestoes_de_teste(
        coluna, presentes, avisos, tamanho_amostra, colunas_em_fk_composta
    )
    if testes:
        entrada["tests"] = testes
    return entrada


def _testes_de_modelo(
    tabela: TabelaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis no nível do model (tabela).

    Diferente de `_sugestoes_de_teste` (nível coluna), dois testes vivem
    aqui — ambos fatos estruturais do catálogo, com severidade padrão
    (`error`), não `warn` como `accepted_values` (não há razão estatística
    pra suavizar um fato estrutural):

    - `dbt_utils.unique_combination_of_columns` — um por `RestricaoUnica`
      (UNIQUE composto real do schema, issue #89).
    - `composite_relationships` — um por `RestricaoDeFkComposta` (FK
      composta real do schema, issue #95), só quando a tabela referenciada
      está no lote (mesma regra do `relationships` single-column); senão,
      `Aviso` + omissão.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado —
            usado só pela checagem de `composite_relationships`.
        avisos: lista de avisos acumulada pelo Gerador, alimentada quando
            uma FK composta referencia tabela fora do lote.

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
            avisos.append(
                Aviso(
                    mensagem=(
                        f"FK composta de '{tabela.nome_escopo}.{tabela.nome_tabela}' "
                        f"({', '.join(restricao_fk.colunas_locais)}) referencia "
                        f"'{chave_referenciada[0]}.{chave_referenciada[1]}', fora do "
                        "lote analisado nesta execução — teste "
                        "composite_relationships omitido."
                    ),
                    origem=_ORIGEM,
                )
            )
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
    tabela: TabelaAnalisada, presentes: set[tuple[str, str]], avisos: list[Aviso]
) -> dict[str, Any]:
    """Monta a entrada de um staging model em `schema.yml`.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        avisos: lista de avisos acumulada pelo Gerador.

    Returns:
        Dict com `name`, `description` opcional, `tests` opcional
        (model-level, ver `_testes_de_modelo`) e a lista de `columns`.
    """
    nome_model = _nome_model(tabela.nome_escopo, tabela.nome_tabela)
    entrada: dict[str, Any] = {"name": nome_model}
    if tabela.papel_de_negocio:
        entrada["description"] = tabela.papel_de_negocio
    testes_de_modelo = _testes_de_modelo(tabela, presentes, avisos)
    if testes_de_modelo:
        entrada["tests"] = testes_de_modelo
    tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
    colunas_em_fk_composta: set[str] = set()
    for restricao in tabela.restricoes_fk_compostas:
        colunas_em_fk_composta.update(restricao.colunas_locais)
    entrada["columns"] = [
        _coluna_schema_yaml(
            coluna, presentes, avisos, tamanho_amostra, colunas_em_fk_composta
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
) -> str:
    """Renderiza o README.md do projeto dbt gerado, na raiz do projeto.

    Args:
        tabelas_por_escopo: tabelas do lote, já agrupadas por escopo
            (`_agrupar_por_escopo`).
        gerado_em: timestamp ISO 8601 da execução, compartilhado com
            `dbt_project.yml`.
        usa_dbt_utils: se `packages.yml` foi gerado nesta execução — o bloco
            de comandos só menciona `dbt deps` quando há dependência real
            a instalar (issue #89).
        usa_matches_format: se `macros/matches_format/` foi gerado nesta
            execução — a nota sobre engines suportadas (Postgres/MariaDB
            nesta v1) só aparece quando há consumidor real (issue #90).

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
    )


def _dump_yaml(conteudo: dict[str, Any]) -> str:
    """Serializa um dict em YAML determinístico (ordem preservada, unicode)."""
    return yaml.safe_dump(conteudo, sort_keys=False, allow_unicode=True)

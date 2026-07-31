"""Montagem do chunk JSON de uma única tabela, escopo single-tabela."""

import json
from typing import Any

from ddf.domain.model.analysis import (
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
)
from ddf.infrastructure.adapters.generators.comum._metricas import (
    _cobertura_dos_valores_frequentes,
    _elegivel_para_enumeracao,
)


def _nome_arquivo(tabela: str) -> str:
    """Nome do arquivo de uma tabela dentro da subpasta do seu escopo: `<tabela>.json`.

    Sem prefixo de escopo — a subpasta `tabelas/<escopo>/` já desambigua
    tabela homônima entre escopos, ao contrário do `_nome_model` do
    `GeradorDbt` (namespace global de model no grafo dbt).

    Args:
        tabela: `nome_tabela` da tabela.

    Returns:
        Nome do arquivo dentro de `tabelas/<escopo>/`.
    """
    return f"{tabela}.json"


def _metrica_de_coluna(coluna: ColunaAnalisada) -> MetricasBaseColuna | None:
    """Filtra a MetricasBaseColuna de uma coluna, se ela já tiver sido calculada."""
    metricas = [m for m in coluna.metricas if isinstance(m, MetricasBaseColuna)]
    return metricas[0] if metricas else None


def _metrica_de_tabela(tabela: TabelaAnalisada) -> MetricasBaseTabela | None:
    """Filtra a MetricasBaseTabela de uma tabela, se ela já tiver sido calculada."""
    metricas = [m for m in tabela.metricas if isinstance(m, MetricasBaseTabela)]
    return metricas[0] if metricas else None


def _sugestao_de_filtro(
    coluna: ColunaAnalisada, tamanho_amostra: int
) -> dict[str, Any] | None:
    """Sugere um filtro `enum` para a coluna, se a amostra sustentar a enumeração.

    Reaproveita `_elegivel_para_enumeracao` (issue #95, mesma pergunta
    resolvida pelo `GeradorDbt` para `accepted_values`): categoria de dado
    não monotônica/incompatível, piso de amostra, teto de cardinalidade real,
    `percentual_unico < 10.0` e cobertura dos top-10 valores não-nulos.
    Colunas já `chave_primaria=True` nunca entram: PK é identificador, não
    filtro de enum — checagem específica deste Gerador, fora da função
    compartilhada (não é sobre "isso é enumerável", é sobre "isso é um
    filtro de UI útil").

    Args:
        coluna: coluna analisada a avaliar.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        Dict com `coluna`, `tipo`, `valores` e `cobertura_amostral`, ou
        `None` se a coluna não atingir os critérios.
    """
    if coluna.chave_primaria:
        return None
    metrica = _metrica_de_coluna(coluna)
    elegivel = metrica is not None and _elegivel_para_enumeracao(
        coluna, metrica, tamanho_amostra
    )
    if metrica is None or not elegivel:
        return None
    return {
        "coluna": coluna.nome,
        "tipo": "enum",
        "valores": [valor for valor, _ in metrica.valores_frequentes],
        "cobertura_amostral": round(
            _cobertura_dos_valores_frequentes(metrica, tamanho_amostra), 4
        ),
    }


def _serializar_metricas_coluna(
    metrica: MetricasBaseColuna | None,
) -> dict[str, Any] | None:
    """Serializa a MetricasBaseColuna de uma coluna, se presente."""
    if metrica is None:
        return None
    return {
        "percentual_nulo": metrica.percentual_nulo,
        "percentual_unico": metrica.percentual_unico,
        "valores_frequentes": [list(par) for par in metrica.valores_frequentes],
        "minimo": metrica.minimo,
        "maximo": metrica.maximo,
        "formato_detectado": metrica.formato_detectado,
    }


def _serializar_coluna(coluna: ColunaAnalisada) -> dict[str, Any]:
    """Serializa uma ColunaAnalisada para o chunk da tabela."""
    return {
        "nome": coluna.nome,
        "tipo_dado": coluna.tipo_dado.model_dump(mode="json", exclude_none=True),
        "chave_primaria": coluna.chave_primaria,
        "chave_estrangeira": coluna.chave_estrangeira,
        "referencia": (
            coluna.referencia.model_dump(mode="json")
            if coluna.referencia is not None
            else None
        ),
        "nao_nulavel": coluna.nao_nulavel,
        "unica": coluna.unica,
        "papel_de_negocio": coluna.papel_de_negocio,
        "regras_de_negocio": coluna.regras_de_negocio,
        "metricas": _serializar_metricas_coluna(_metrica_de_coluna(coluna)),
    }


def _montar_tabela_json(tabela: TabelaAnalisada) -> dict[str, Any]:
    """Monta o chunk completo de uma tabela: dados, métricas e esquema de consulta.

    Args:
        tabela: tabela analisada a serializar.

    Returns:
        Dict pronto para `json.dumps`. `metricas_tabela` fica ausente se a
        tabela não tiver `MetricasBaseTabela` calculada; quando presente,
        carrega `amostra_vazia` ao lado de `completude` — sem essa flag, um
        agente consumidor não tem como distinguir "100% de completude
        confirmada pela amostra" de "nenhuma linha inspecionada"
        já que o valor numérico de `completude` é o mesmo nos dois
        casos. `esquema_de_consulta` fica ausente se nenhuma coluna sugerir
        filtro de enum. `restricoes_unicas` fica ausente se a tabela não
        tem UNIQUE composto; quando presente, é lista de listas de nomes de
        coluna (não lista de dicts nomeados) — `RestricaoUnica` só carrega
        `colunas`, sem metadado adicional que justifique um wrapper, ao
        contrário das arestas de `grafo_de_relacionamentos`. Grupos
        ordenados por `colunas` — a ordem de extração vem do catálogo
        (posição do índice), sem significado humano, e reextrações do
        mesmo schema lógico não deveriam gerar diff espúrio no artefato
        versionado. `restricoes_fk_compostas` (issue #95) segue o mesmo
        princípio de omissão, mas é lista de dicts — `RestricaoDeFkComposta`
        carrega 4 campos (colunas locais/referenciadas + escopo/tabela
        referenciados), sem estrutura simples o bastante pra virar lista de
        listas sem perder informação.
    """
    tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
    conteudo: dict[str, Any] = {
        "nome_tabela": tabela.nome_tabela,
        "nome_escopo": tabela.nome_escopo,
        "papel_de_negocio": tabela.papel_de_negocio,
        "regras_de_negocio": tabela.regras_de_negocio,
        "total_linhas": tabela.total_linhas,
        "metadados_amostra": {
            "estrategia": tabela.metadados_amostra.estrategia,
            "tamanho_amostra": tamanho_amostra,
            "percentual": tabela.metadados_amostra.percentual,
            "seed": tabela.metadados_amostra.seed,
        },
    }

    metrica_tabela = _metrica_de_tabela(tabela)
    if metrica_tabela is not None:
        conteudo["metricas_tabela"] = {
            "completude": metrica_tabela.completude,
            "amostra_vazia": tamanho_amostra == 0,
        }

    if tabela.restricoes_unicas:
        conteudo["restricoes_unicas"] = [
            list(restricao.colunas)
            for restricao in sorted(tabela.restricoes_unicas, key=lambda r: r.colunas)
        ]

    if tabela.restricoes_fk_compostas:
        grupos_fk = sorted(
            tabela.restricoes_fk_compostas, key=lambda r: r.colunas_locais
        )
        conteudo["restricoes_fk_compostas"] = [
            {
                "colunas_locais": list(restricao.colunas_locais),
                "escopo_referenciado": restricao.nome_escopo_referenciado,
                "tabela_referenciada": restricao.nome_tabela_referenciada,
                "colunas_referenciadas": list(restricao.colunas_referenciadas),
            }
            for restricao in grupos_fk
        ]

    conteudo["colunas"] = [_serializar_coluna(coluna) for coluna in tabela.colunas]

    filtros = [
        sugestao
        for coluna in tabela.colunas
        if (sugestao := _sugestao_de_filtro(coluna, tamanho_amostra)) is not None
    ]
    if filtros:
        conteudo["esquema_de_consulta"] = {"colunas_filtraveis": filtros}

    return conteudo


def _dump_json(conteudo: dict[str, Any]) -> str:
    """Serializa um dict em JSON determinístico (ordem de inserção, unicode)."""
    return json.dumps(conteudo, ensure_ascii=False, indent=2, sort_keys=False)

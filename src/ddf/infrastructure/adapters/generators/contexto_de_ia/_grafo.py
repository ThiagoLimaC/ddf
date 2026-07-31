"""Grafo bidirecional de relacionamentos via FK real, escopo cross-tabela."""

from typing import Any

from ddf.domain.model.analysis import TabelaAnalisada

_NOTA_DE_ESCOPO_DO_GRAFO = (
    "referenciado_por reflete apenas as tabelas presentes neste lote de "
    "análise; se o lote for um subconjunto da fonte, tabelas fora dele que "
    "também referenciam a mesma tabela não aparecem aqui."
)


def _chave_tabela(escopo: str, tabela: str) -> str:
    """Chave lógica de uma tabela no grafo de relacionamentos: `escopo.tabela`."""
    return f"{escopo}.{tabela}"


def _montar_grafo(tabelas: list[TabelaAnalisada]) -> dict[str, Any]:
    """Monta o grafo bidirecional de relacionamentos via FK real.

    `referencia` (saída) é sempre incluída quando a coluna tem
    `chave_estrangeira=True`, mesmo se a tabela destino não estiver no lote
    analisado — é informação estrutural conhecida (FK real do catálogo, não
    heurística de nome), não uma garantia de execução como o `relationships`
    do dbt. Por vir do FK da própria tabela (que está sendo iterada porque
    está no lote), é sempre exaustiva.

    `referenciado_por` (entrada) é fundamentalmente diferente: só existe
    porque outras tabelas do lote foram inspecionadas e apontavam pra essa.
    Se o lote for um subconjunto do banco, uma tabela fora dele que também
    referencia a mesma tabela fica invisível — a lista pode aparecer
    **não-vazia mas incompleta**, o que é pior que vazia (convida conclusão
    errada de exaustividade). Como essa limitação é estrutural de toda
    execução (não um caso pontual), não vira `Aviso` por ocorrência — vira
    uma nota fixa (`_NOTA_DE_ESCOPO_DO_GRAFO`) sempre presente no artefato,
    no mesmo espírito da nota de rodapé de `MetadadosDeAmostra` no
    `GeradorMarkdown` ("isto é amostra, não população").

    Args:
        tabelas: tabelas do lote analisado, já ordenadas por
            `(nome_escopo, nome_tabela)`.

    Returns:
        Dict com `nota_de_escopo` e `tabelas`
        (`{chave_da_tabela: {"referencia": [...], "referenciado_por": [...]}}`,
        omitindo as duas listas quando vazias).
    """
    grafo: dict[str, dict[str, list[dict[str, str]]]] = {
        _chave_tabela(tabela.nome_escopo, tabela.nome_tabela): {
            "referencia": [],
            "referenciado_por": [],
        }
        for tabela in tabelas
    }

    for tabela in tabelas:
        chave_origem = _chave_tabela(tabela.nome_escopo, tabela.nome_tabela)
        for coluna in tabela.colunas:
            if not coluna.chave_estrangeira or coluna.referencia is None:
                continue
            referencia = coluna.referencia
            grafo[chave_origem]["referencia"].append(
                {
                    "coluna": coluna.nome,
                    "tabela_destino": _chave_tabela(
                        referencia.nome_escopo, referencia.nome_tabela
                    ),
                    "coluna_destino": referencia.nome_coluna,
                }
            )
            chave_destino = _chave_tabela(
                referencia.nome_escopo, referencia.nome_tabela
            )
            if chave_destino in grafo:
                grafo[chave_destino]["referenciado_por"].append(
                    {
                        "tabela_origem": chave_origem,
                        "coluna_origem": coluna.nome,
                        "coluna": referencia.nome_coluna,
                    }
                )

    return {
        "nota_de_escopo": _NOTA_DE_ESCOPO_DO_GRAFO,
        "tabelas": {
            chave: {
                direcao: arestas for direcao, arestas in entradas.items() if arestas
            }
            for chave, entradas in grafo.items()
        },
    }

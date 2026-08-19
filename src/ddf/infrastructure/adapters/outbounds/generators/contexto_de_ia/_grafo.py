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

    `referencia` (saída) é sempre exaustiva — vem do FK real da própria
    tabela, mesmo se a tabela destino não estiver no lote. `referenciado_por`
    (entrada) é estruturalmente incompleto se o lote for um subconjunto do
    banco (tabela fora do lote que também referencia esta fica invisível) —
    por isso não vira `Aviso` pontual, vira a nota fixa
    `_NOTA_DE_ESCOPO_DO_GRAFO`, sempre presente no artefato.

    Detalhes e comparação com `MetadadosDeAmostra`: `docs/low_level_design.md`,
    seção `GeradorContextoDeIA`.

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
            if not coluna.chave_estrangeira:
                continue
            for referencia in coluna.referencias:
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

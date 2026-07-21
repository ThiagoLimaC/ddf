"""GeradorContextoDeIA: contexto navegável por tabela, pensado para consumo por agente.

Em vez de um único `ai_context.json` com o `BancoAnalisado` inteiro
serializado (redundante com Markdown/dbt — mesma informação, outro parser),
o artefato é dividido em um `index.json` leve com o grafo de relacionamentos
via FK real, e um arquivo por tabela em `tabelas/<escopo>__<tabela>.json`
(mesma convenção de nome de `_nome_model` do `GeradorDbt`) — permite a um
agente carregar só o subconjunto do schema relevante à tarefa (schema
linking), em vez do banco inteiro.
"""

import json
from pathlib import Path
from typing import Any

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators._metricas import (
    _COBERTURA_MINIMA_ACCEPTED_VALUES,
    _cobertura_dos_valores_frequentes,
)

_TAMANHO_AMOSTRA_MINIMO_ENUM = 100


def _nome_arquivo(escopo: str, tabela: str) -> str:
    """Nome do arquivo por tabela: `<escopo>__<tabela>.json`.

    Mesma convenção de duplo underscore do `_nome_model` do `GeradorDbt` —
    evita colisão entre escopos com tabela de mesmo nome, sem inventar uma
    segunda convenção de nomenclatura no produto.

    Args:
        escopo: `nome_escopo` da tabela.
        tabela: `nome_tabela` da tabela.

    Returns:
        Nome do arquivo, único mesmo quando dois escopos têm tabela homônima.
    """
    return f"{escopo}__{tabela}.json"


def _chave_tabela(escopo: str, tabela: str) -> str:
    """Chave lógica de uma tabela no grafo de relacionamentos: `escopo.tabela`."""
    return f"{escopo}.{tabela}"


def _metrica_de_coluna(coluna: ColunaAnalisada) -> MetricasBaseColuna | None:
    """Filtra a MetricasBaseColuna de uma coluna, se ela já tiver sido calculada."""
    metricas = [m for m in coluna.metricas if isinstance(m, MetricasBaseColuna)]
    return metricas[0] if metricas else None


def _metrica_de_tabela(tabela: TabelaAnalisada) -> MetricasBaseTabela | None:
    """Filtra a MetricasBaseTabela de uma tabela, se ela já tiver sido calculada."""
    metricas = [m for m in tabela.metricas if isinstance(m, MetricasBaseTabela)]
    return metricas[0] if metricas else None


_NOTA_DE_ESCOPO_DO_GRAFO = (
    "referenciado_por reflete apenas as tabelas presentes neste lote de "
    "análise; se o lote for um subconjunto da fonte, tabelas fora dele que "
    "também referenciam a mesma tabela não aparecem aqui."
)


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


def _sugestao_de_filtro(
    coluna: ColunaAnalisada, tamanho_amostra: int
) -> dict[str, Any] | None:
    """Sugere um filtro `enum` para a coluna, se a amostra sustentar a enumeração.

    Reaproveita `_cobertura_dos_valores_frequentes` (mesma pergunta
    estatística já resolvida pelo `GeradorDbt` para `accepted_values`):
    exige `percentual_unico < 10.0` (parece categórica), cobertura dos
    top-10 valores não-nulos `>= _COBERTURA_MINIMA_ACCEPTED_VALUES`, e um
    piso de `tamanho_amostra >= _TAMANHO_AMOSTRA_MINIMO_ENUM` (mesmo piso já
    usado pelo AnalisadorDeMetricasDeColuna para emitir Aviso de baixo sinal)
    — sem o piso, uma amostra pequena pode parecer 100% categórica só por
    coincidência de tamanho. Colunas já `chave_primaria=True` nunca entram:
    PK é identificador, não filtro de enum.

    Args:
        coluna: coluna analisada a avaliar.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        Dict com `coluna`, `tipo`, `valores` e `cobertura_amostral`, ou
        `None` se a coluna não atingir os critérios.
    """
    if coluna.chave_primaria or tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_ENUM:
        return None
    metrica = _metrica_de_coluna(coluna)
    if metrica is None or not metrica.valores_frequentes:
        return None
    if metrica.percentual_unico >= 10.0:
        return None
    cobertura = _cobertura_dos_valores_frequentes(metrica, tamanho_amostra)
    if cobertura < _COBERTURA_MINIMA_ACCEPTED_VALUES:
        return None
    return {
        "coluna": coluna.nome,
        "tipo": "enum",
        "valores": [valor for valor, _ in metrica.valores_frequentes],
        "cobertura_amostral": round(cobertura, 4),
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
        tabela não tiver `MetricasBaseTabela` calculada; `esquema_de_consulta`
        fica ausente se nenhuma coluna sugerir filtro de enum.
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
        },
    }

    metrica_tabela = _metrica_de_tabela(tabela)
    if metrica_tabela is not None:
        conteudo["metricas_tabela"] = {"completude": metrica_tabela.completude}

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


class GeradorContextoDeIA:
    """Gera contexto navegável por tabela, pensado para consumo por agente de IA."""

    requer: list[TipoDeMetrica] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Escreve `index.json` (grafo de relacionamentos) e um chunk por tabela.

        Args:
            entrada: banco analisado cujas tabelas já devem ter
                MetricasBaseColuna calculada.
            destino: diretório raiz do contexto gerado.

        Returns:
            Sucesso(None) sem avisos, ou Falha na primeira escrita em disco
            que falhar.
        """
        tabelas = sorted(entrada.tabelas, key=lambda t: (t.nome_escopo, t.nome_tabela))

        indice: dict[str, Any] = {
            "tabelas": [
                {
                    "nome_escopo": tabela.nome_escopo,
                    "nome_tabela": tabela.nome_tabela,
                    "arquivo": (
                        "tabelas/"
                        + _nome_arquivo(tabela.nome_escopo, tabela.nome_tabela)
                    ),
                }
                for tabela in tabelas
            ],
            "grafo_de_relacionamentos": _montar_grafo(tabelas),
        }
        resultado_indice = escrever_arquivo(
            destino / "index.json", _dump_json(indice)
        )
        if isinstance(resultado_indice, Falha):
            return resultado_indice

        for tabela in tabelas:
            caminho_tabela = destino / "tabelas" / _nome_arquivo(
                tabela.nome_escopo, tabela.nome_tabela
            )
            resultado_tabela = escrever_arquivo(
                caminho_tabela, _dump_json(_montar_tabela_json(tabela))
            )
            if isinstance(resultado_tabela, Falha):
                return resultado_tabela

        return Sucesso(None)

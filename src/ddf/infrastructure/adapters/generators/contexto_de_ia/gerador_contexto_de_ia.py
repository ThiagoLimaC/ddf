"""GeradorContextoDeIA: contexto navegável por tabela, pensado para consumo por agente.

Em vez de um único `ai_context.json` com o `BancoAnalisado` inteiro
serializado (redundante com Markdown/dbt — mesma informação, outro parser),
o artefato é dividido em um `index.json` leve com o grafo de relacionamentos
via FK real, e um arquivo por tabela em `tabelas/<escopo>/<tabela>.json` —
permite a um agente carregar só o subconjunto do schema relevante à tarefa
(schema linking), em vez do banco inteiro. Diferente do `_nome_model` do
`GeradorDbt` (que precisa de nome globalmente único no grafo dbt, daí o
`stg_<escopo>__<tabela>`), aqui a própria subpasta por escopo já desambigua
tabela homônima entre escopos — sem necessidade do prefixo redundante no
nome do arquivo.

Módulo reduzido a orquestração — grafo de relacionamentos (escopo
cross-tabela) em `_grafo.py`, montagem do chunk por tabela (escopo
single-tabela) em `_serializacao.py`.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ddf.domain.model.analysis import (
    BancoAnalisado,
    MetricasBaseColuna,
    MetricasDeConfianca,
    TipoDeMetrica,
)
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators.comum._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators.contexto_de_ia._grafo import _montar_grafo
from ddf.infrastructure.adapters.generators.contexto_de_ia._serializacao import (
    _dump_json,
    _montar_tabela_json,
    _nome_arquivo,
)


class GeradorContextoDeIA:
    """Gera contexto navegável por tabela, pensado para consumo por agente de IA."""

    requer: list[TipoDeMetrica] = [MetricasBaseColuna, MetricasDeConfianca]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Escreve `index.json` (grafo de relacionamentos) e um chunk por tabela.

        Cada tabela vai para `tabelas/<escopo>/<tabela>.json` — subpasta por
        escopo, mesma organização já usada pelo `GeradorDbt`.

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
            "generated_at": datetime.now(UTC).isoformat(),
            "tabelas": [
                {
                    "nome_escopo": tabela.nome_escopo,
                    "nome_tabela": tabela.nome_tabela,
                    "arquivo": (
                        f"tabelas/{tabela.nome_escopo}/"
                        f"{_nome_arquivo(tabela.nome_tabela)}"
                    ),
                }
                for tabela in tabelas
            ],
            "grafo_de_relacionamentos": _montar_grafo(tabelas),
        }
        resultado_indice = escrever_arquivo(destino / "index.json", _dump_json(indice))
        if isinstance(resultado_indice, Falha):
            return resultado_indice

        for tabela in tabelas:
            caminho_tabela = (
                destino
                / "tabelas"
                / tabela.nome_escopo
                / _nome_arquivo(tabela.nome_tabela)
            )
            resultado_tabela = escrever_arquivo(
                caminho_tabela, _dump_json(_montar_tabela_json(tabela))
            )
            if isinstance(resultado_tabela, Falha):
                return resultado_tabela

        return Sucesso(None)

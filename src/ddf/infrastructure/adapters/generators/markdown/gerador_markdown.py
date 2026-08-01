"""GeradorMarkdown: documentação navegável em Markdown a partir do BancoAnalisado."""

from datetime import UTC, datetime
from pathlib import Path

from ddf.domain.model.analysis import (
    BancoAnalisado,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TipoDeMetrica,
)
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators.comum._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators.markdown._filtros import (
    _colunas_com_fk_composta,
    _colunas_com_restricao_composta,
)
from ddf.infrastructure.adapters.generators.markdown._templates import (
    _TEMPLATE_INDEX,
    _TEMPLATE_TABELA,
)


class GeradorMarkdown:
    """Gera um `.md` por tabela e um `index.md` a partir do BancoAnalisado."""

    requer: list[TipoDeMetrica] = [MetricasBaseColuna, MetricasBaseTabela]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Escreve a documentação Markdown de cada tabela e o índice geral.

        Args:
            entrada: banco analisado cujas tabelas já devem ter
                MetricasBaseColuna/MetricasBaseTabela calculadas.
            destino: diretório raiz onde os artefatos serão escritos.

        Returns:
            Sucesso(None) com Aviso por tabela sem papel_de_negocio, ou
            Falha na primeira escrita em disco que falhar.
        """
        gerado_em = datetime.now(UTC).isoformat()
        avisos: list[Aviso] = []
        for tabela in entrada.tabelas:
            caminho_tabela = destino / tabela.nome_escopo / f"{tabela.nome_tabela}.md"
            conteudo = _TEMPLATE_TABELA.render(
                tabela=tabela,
                gerado_em=gerado_em,
                colunas_compostas=_colunas_com_restricao_composta(tabela),
                colunas_fk_compostas=_colunas_com_fk_composta(tabela),
            )
            resultado = escrever_arquivo(caminho_tabela, conteudo)
            if isinstance(resultado, Falha):
                return resultado
            if tabela.papel_de_negocio is None:
                avisos.append(
                    Aviso(
                        mensagem=(
                            f"Tabela '{tabela.nome_escopo}.{tabela.nome_tabela}' "
                            "sem papel_de_negocio."
                        ),
                        origem="GeradorMarkdown",
                    )
                )

        ordenadas = sorted(
            entrada.tabelas, key=lambda t: (t.nome_escopo, t.nome_tabela)
        )
        conteudo_index = _TEMPLATE_INDEX.render(tabelas=ordenadas, gerado_em=gerado_em)
        resultado_index = escrever_arquivo(destino / "index.md", conteudo_index)
        if isinstance(resultado_index, Falha):
            return resultado_index

        return Sucesso(None, avisos=avisos)

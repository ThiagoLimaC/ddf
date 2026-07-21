"""GeradorMarkdown: documentação navegável em Markdown a partir do BancoAnalisado."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators._escrita import escrever_arquivo

_NAO_DISPONIVEL = "N/D"
_NAO_APLICAVEL = "—"

_CATEGORIAS_SEM_MINIMO_E_MAXIMO = {
    CategoriaDeDado.VARCHAR,
    CategoriaDeDado.CHAR,
    CategoriaDeDado.TEXT,
    CategoriaDeDado.UUID,
    CategoriaDeDado.ENUM,
    CategoriaDeDado.SET,
    CategoriaDeDado.BOOLEAN,
    CategoriaDeDado.JSON,
    CategoriaDeDado.ARRAY,
    CategoriaDeDado.UNKNOWN,
}

_GARANTIDO_PELO_SCHEMA = "0.00% (garantido pelo schema)"
_SEM_EVIDENCIA = "sem evidência (amostra vazia)"

_CATEGORIAS_COM_PRECISAO_ESCALA = {CategoriaDeDado.NUMERIC}
_CATEGORIAS_COM_TAMANHO_MAXIMO = {CategoriaDeDado.VARCHAR}
_CATEGORIAS_COM_TAMANHO_FIXO = {CategoriaDeDado.CHAR}
_CATEGORIAS_COM_TIMEZONE = {CategoriaDeDado.TIMESTAMP, CategoriaDeDado.TIME}
_CATEGORIAS_COM_VALORES_PERMITIDOS = {CategoriaDeDado.ENUM, CategoriaDeDado.SET}


def _escapar_celula(valor: str) -> str:
    r"""Filtro Jinja: escapa `|` literal para não quebrar a tabela Markdown.

    Args:
        valor: texto a ser inserido em uma célula.

    Returns:
        Texto com `|` substituído por `\|`.
    """
    return valor.replace("|", "\\|")


def _formatar_tipo(tipo: TipoDeDado) -> str:
    """Filtro Jinja: formata um TipoDeDado com seus atributos de precisão.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        Representação textual do tipo, ex.: `NUMERIC(10,2)`, `VARCHAR(255)`,
        `TIMESTAMP WITH TIME ZONE`, ou só a categoria quando não há atributo
        de precisão aplicável.
    """
    categoria = tipo.categoria

    if categoria in _CATEGORIAS_COM_PRECISAO_ESCALA and tipo.precisao is not None:
        return f"{categoria.value}({tipo.precisao},{tipo.escala or 0})"
    if categoria in _CATEGORIAS_COM_TAMANHO_MAXIMO and tipo.tamanho_maximo is not None:
        return f"{categoria.value}({tipo.tamanho_maximo})"
    if categoria in _CATEGORIAS_COM_TAMANHO_FIXO and tipo.tamanho_fixo is not None:
        return f"{categoria.value}({tipo.tamanho_fixo})"
    if categoria in _CATEGORIAS_COM_TIMEZONE and tipo.com_timezone:
        return f"{categoria.value} WITH TIME ZONE"
    if categoria in _CATEGORIAS_COM_VALORES_PERMITIDOS and tipo.valores_permitidos:
        return f"{categoria.value}({', '.join(tipo.valores_permitidos)})"
    if categoria == CategoriaDeDado.ARRAY:
        elemento = tipo.elemento.value if tipo.elemento is not None else "UNKNOWN"
        return f"{elemento}[]"

    return str(categoria.value)


def _marcadores_de_restricao(coluna: ColunaAnalisada) -> str:
    """Filtro Jinja: combina PK, FK, UNIQUE e NOT NULL numa mesma coluna.

    Args:
        coluna: coluna analisada.

    Returns:
        "PK", "FK → escopo.tabela.coluna", "UNIQUE", "NOT NULL", combinados
        por vírgula conforme aplicável, ou string vazia se a coluna não tem
        nenhuma restrição real do schema. "UNIQUE"/"NOT NULL" são omitidos
        quando a coluna já é PK — PK implica único e não-nulo, marcar os
        dois seria redundante.
    """
    marcadores: list[str] = []
    if coluna.chave_primaria:
        marcadores.append("PK")
    if coluna.chave_estrangeira and coluna.referencia is not None:
        referencia = coluna.referencia
        marcadores.append(
            f"FK → {referencia.nome_escopo}.{referencia.nome_tabela}."
            f"{referencia.nome_coluna}"
        )
    if coluna.unica and not coluna.chave_primaria:
        marcadores.append("UNIQUE")
    if coluna.nao_nulavel and not coluna.chave_primaria:
        marcadores.append("NOT NULL")
    return ", ".join(marcadores)


def _metrica_de_coluna(coluna: ColunaAnalisada) -> MetricasBaseColuna | None:
    """Filtra a MetricasBaseColuna de uma coluna, se ela já tiver sido calculada.

    Args:
        coluna: coluna analisada.

    Returns:
        A MetricasBaseColuna encontrada, ou None se ausente.
    """
    metricas_coluna = [m for m in coluna.metricas if isinstance(m, MetricasBaseColuna)]
    return metricas_coluna[0] if metricas_coluna else None


def _formatar_completude(tabela: TabelaAnalisada) -> str:
    """Filtro Jinja: formata a completude da tabela, se já tiver sido calculada.

    Args:
        tabela: tabela analisada a documentar.

    Returns:
        "sem evidência (amostra vazia)" se `tamanho_amostra == 0` — 100%
        de completude nesse caso seria "nenhuma linha inspecionada", não
        "nenhum nulo encontrado", uma afirmação que a amostra não sustenta.
        Senão, completude formatada como percentual, ou "N/D" se a métrica
        ainda não tiver sido calculada.
    """
    if tabela.metadados_amostra.tamanho_amostra == 0:
        return _SEM_EVIDENCIA
    metricas_tabela = [m for m in tabela.metricas if isinstance(m, MetricasBaseTabela)]
    if not metricas_tabela:
        return _NAO_DISPONIVEL
    return f"{metricas_tabela[0].completude:.2f}%"


def _formatar_extremo(valor: str | None, aplicavel: bool) -> str:
    """Formata um valor de mínimo/máximo, respeitando a supressão por categoria.

    Args:
        valor: mínimo ou máximo já calculado pelo Analisador.
        aplicavel: se a categoria da coluna admite mínimo/máximo com
            significado de negócio.

    Returns:
        "—" se não aplicável à categoria, "N/D" se aplicável mas ausente,
        ou o próprio valor.
    """
    if not aplicavel:
        return _NAO_APLICAVEL
    return valor if valor is not None else _NAO_DISPONIVEL


def _linha_qualidade(coluna: ColunaAnalisada, tamanho_amostra: int) -> dict[str, str]:
    """Filtro Jinja: monta os campos formatados de uma linha de qualidade dos dados.

    Mínimo/máximo saem como "—" (não aplicável) para categorias em que a
    ordenação do Polars não tem significado de negócio (texto, UUID,
    enum/set, booleano) — mostrar um valor ali seria mais enganoso do que
    não mostrar nada, já que a ordenação é lexicográfica, não a esperada.

    Args:
        coluna: coluna analisada a documentar.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        Nome e as métricas de qualidade já formatadas/escapadas, com "N/D"
        onde a métrica ainda não foi calculada. `percentual_nulo`/
        `percentual_unico` mostram "sem evidência (amostra vazia)" quando
        `tamanho_amostra == 0` — 0.00% nesse caso seria "nenhuma linha
        inspecionada", não "nenhum nulo/duplicata encontrado". `nao_nulavel`
        tem precedência sobre isso: "0.00% (garantido pelo schema)" é
        garantia do catálogo, não estimativa sobre a amostra, então vale
        mesmo sem evidência amostral.
    """
    aplicavel = coluna.tipo_dado.categoria not in _CATEGORIAS_SEM_MINIMO_E_MAXIMO
    metrica = _metrica_de_coluna(coluna)

    percentual_nulo = percentual_unico = formato = _NAO_DISPONIVEL
    minimo = maximo = _formatar_extremo(None, aplicavel)
    if metrica is not None:
        percentual_nulo = f"{metrica.percentual_nulo:.2f}%"
        percentual_unico = f"{metrica.percentual_unico:.2f}%"
        minimo = _formatar_extremo(metrica.minimo, aplicavel)
        maximo = _formatar_extremo(metrica.maximo, aplicavel)
        formato = metrica.formato_detectado or _NAO_DISPONIVEL
    if tamanho_amostra == 0:
        percentual_nulo = percentual_unico = _SEM_EVIDENCIA
    if coluna.nao_nulavel:
        percentual_nulo = _GARANTIDO_PELO_SCHEMA

    return {
        "nome": _escapar_celula(coluna.nome),
        "percentual_nulo": percentual_nulo,
        "percentual_unico": percentual_unico,
        "minimo": _escapar_celula(minimo),
        "maximo": _escapar_celula(maximo),
        "formato": _escapar_celula(formato),
    }


def _secoes_valores_frequentes(
    colunas: list[ColunaAnalisada], tamanho_amostra: int
) -> list[dict[str, Any]]:
    """Filtro Jinja: monta as subseções de valores frequentes, uma por coluna.

    Fora da tabela principal de propósito: uma lista de N pares valor/
    contagem tem tamanho variável e não cabe em largura fixa de célula sem
    prejudicar a leitura do resto da tabela.

    Args:
        colunas: colunas da tabela a documentar.
        tamanho_amostra: total de linhas amostradas, para calcular o
            percentual de cada valor frequente sobre a amostra.

    Returns:
        Uma entrada por coluna que tem MetricasBaseColuna e (a) tem
        valores_frequentes não vazio, ou (b) é 100% nula na amostra — nesse
        caso a lista de fato não existe, e omitir a coluna em silêncio
        pareceria uma omissão do Gerador, não um fato sobre o dado. Colunas
        com métrica ausente continuam omitidas. Inclui `chave_primaria` e
        `unica` (lista tende a ser só ruído nos dois casos: contagem 1 em
        quase todo valor) e `totalmente_nulo` para o template escolher a nota
        certa — PK tem precedência sobre UNIQUE quando as duas são
        verdadeiras, pra não duplicar o aviso (PK implica único).
    """
    secoes = []
    for coluna in colunas:
        metrica = _metrica_de_coluna(coluna)
        if metrica is None:
            continue
        totalmente_nulo = metrica.percentual_nulo == 100.0
        if not metrica.valores_frequentes and not totalmente_nulo:
            continue

        itens = []
        for valor, contagem in metrica.valores_frequentes:
            percentual = (
                f"{contagem / tamanho_amostra * 100:.2f}%"
                if tamanho_amostra > 0
                else _NAO_DISPONIVEL
            )
            itens.append(
                {
                    "valor": _escapar_celula(valor),
                    "contagem": contagem,
                    "percentual": percentual,
                }
            )
        secoes.append(
            {
                "nome_coluna": _escapar_celula(coluna.nome),
                "chave_primaria": coluna.chave_primaria,
                "unica": coluna.unica and not coluna.chave_primaria,
                "totalmente_nulo": totalmente_nulo,
                "itens": itens,
            }
        )

    return secoes


_ambiente = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 — saída é Markdown, não HTML; escapamos "|" à mão
)
_ambiente.filters["escapar"] = _escapar_celula
_ambiente.filters["formatar_tipo"] = _formatar_tipo
_ambiente.filters["marcadores_de_restricao"] = _marcadores_de_restricao
_ambiente.filters["completude"] = _formatar_completude
_ambiente.filters["linha_qualidade"] = _linha_qualidade
_ambiente.filters["secoes_valores_frequentes"] = _secoes_valores_frequentes
_TEMPLATE_TABELA = _ambiente.get_template("tabela.md.jinja2")
_TEMPLATE_INDEX = _ambiente.get_template("index.md.jinja2")


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
            conteudo = _TEMPLATE_TABELA.render(tabela=tabela, gerado_em=gerado_em)
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

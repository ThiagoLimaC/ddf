"""Funções de formatação usadas como filtro Jinja pelo GeradorMarkdown."""

from typing import Any

from ddf.domain.model.analysis import (
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado

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


def _marcadores_de_restricao(
    coluna: ColunaAnalisada,
    colunas_compostas: frozenset[str],
    colunas_fk_compostas: frozenset[str],
) -> str:
    """Filtro Jinja: combina PK, FK, UNIQUE (simples/composto) e NOT NULL.

    Args:
        coluna: coluna analisada.
        colunas_compostas: nomes de colunas da tabela que participam de
            algum UNIQUE composto (ver `_colunas_com_restricao_composta`).
        colunas_fk_compostas: nomes de colunas da tabela que participam de
            alguma FK composta (ver `_colunas_com_fk_composta`, issue #95).

    Returns:
        "PK", "FK → escopo.tabela.coluna", "FK (composta)", "UNIQUE",
        "UNIQUE (composto)", "NOT NULL", combinados por vírgula conforme
        aplicável, ou string vazia se a coluna não tem nenhuma restrição
        real do schema. "UNIQUE"/"UNIQUE (composto)"/"NOT NULL" são
        omitidos quando a coluna já é PK — PK implica único e não-nulo,
        marcar os dois seria redundante. "UNIQUE (composto)"/
        "FK (composta)" só sinalizam participação — o agrupamento completo
        de colunas está nos bullets de "Restrições UNIQUE compostas"/
        "Chaves estrangeiras compostas" em "Fatos extraídos".
        "FK (composta)" não substitui "FK → ..." — a coluna continua
        mostrando sua própria referência individual, mais o sinal de que
        ela participa de um grupo.
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
    if coluna.nome in colunas_fk_compostas:
        marcadores.append("FK (composta)")
    if coluna.unica and not coluna.chave_primaria:
        marcadores.append("UNIQUE")
    if coluna.nome in colunas_compostas and not coluna.chave_primaria:
        marcadores.append("UNIQUE (composto)")
    if coluna.nao_nulavel and not coluna.chave_primaria:
        marcadores.append("NOT NULL")
    return ", ".join(marcadores)


def _colunas_com_restricao_composta(tabela: TabelaAnalisada) -> frozenset[str]:
    """Nomes de colunas da tabela que participam de algum UNIQUE composto.

    Args:
        tabela: tabela analisada.

    Returns:
        Conjunto de nomes de coluna cobertos por algum `RestricaoUnica` da
        tabela; vazio se a tabela não tem nenhuma constraint composta.
    """
    return frozenset(
        nome for restricao in tabela.restricoes_unicas for nome in restricao.colunas
    )


def _colunas_com_fk_composta(tabela: TabelaAnalisada) -> frozenset[str]:
    """Nomes de colunas locais da tabela que participam de alguma FK composta.

    Args:
        tabela: tabela analisada.

    Returns:
        Conjunto de nomes de coluna cobertos por algum
        `RestricaoDeFkComposta` da tabela; vazio se não houver nenhuma
        (issue #95).
    """
    return frozenset(
        nome
        for restricao in tabela.restricoes_fk_compostas
        for nome in restricao.colunas_locais
    )


def _formatar_restricoes_unicas(tabela: TabelaAnalisada) -> str:
    """Filtro Jinja: formata as constraints UNIQUE compostas da tabela.

    Args:
        tabela: tabela analisada.

    Returns:
        Grupos de colunas formatados como "(`col_a`, `col_b`), (`col_c`,
        `col_d`)", ou string vazia se a tabela não tem nenhuma. Grupos
        ordenados por `colunas` (ordem estável e determinística) — a ordem
        de extração vem do catálogo (posição do índice/OID), sem
        significado humano, e reextrações do mesmo schema lógico não
        deveriam gerar diff espúrio no artefato versionado. Nomes de
        coluna passam por `_escapar_celula` e vão entre crase — identifi-
        cador do Postgres pode conter caractere que quebra ênfase Markdown.
    """
    grupos = sorted(tabela.restricoes_unicas, key=lambda r: r.colunas)
    return ", ".join(
        "(" + ", ".join(f"`{_escapar_celula(nome)}`" for nome in grupo.colunas) + ")"
        for grupo in grupos
    )


def _formatar_restricoes_fk_compostas(tabela: TabelaAnalisada) -> str:
    """Filtro Jinja: formata as FKs compostas da tabela.

    Args:
        tabela: tabela analisada.

    Returns:
        Grupos formatados como "(`pais_id`, `estado_id`) → geografia.estados
        (`pais_id`, `id`)", separados por vírgula, ou string vazia se a
        tabela não tem nenhuma FK composta. Grupos ordenados por
        `colunas_locais` (mesmo motivo de determinismo de
        `_formatar_restricoes_unicas` — issue #95).
    """
    grupos = sorted(tabela.restricoes_fk_compostas, key=lambda r: r.colunas_locais)
    partes: list[str] = []
    for grupo in grupos:
        locais = ", ".join(
            f"`{_escapar_celula(nome)}`" for nome in grupo.colunas_locais
        )
        referenciadas = ", ".join(
            f"`{_escapar_celula(nome)}`" for nome in grupo.colunas_referenciadas
        )
        partes.append(
            f"({locais}) → {grupo.nome_escopo_referenciado}."
            f"{grupo.nome_tabela_referenciada}({referenciadas})"
        )
    return ", ".join(partes)


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

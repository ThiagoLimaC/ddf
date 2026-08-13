"""Lê um cursor de streaming em lotes, sem materializar o resultset inteiro."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

import polars as pl

# Candidatos iniciais, calibrados pelo benchmark da issue #114 — não valores
# finais. TETO_BYTES mira um lote "pequeno" mesmo em tabela larga
# (TEXT/JSON/BYTEA); MINIMO/MAXIMO evitam lote degenerado nos dois extremos
# (tabela muito larga vira poucas linhas por lote, streaming quase inútil;
# tabela muito estreita vira milhões de linhas por lote, streaming inócuo).
_TETO_BYTES_PADRAO = 10_000_000
_MINIMO_PADRAO = 1_000
_MAXIMO_PADRAO = 100_000

# Dois critérios (linhas OU bytes) em vez de um só: um limiar de bytes
# sozinho depende da estimativa de largura média, que cai num fallback
# conservador quando a tabela nunca foi analisada — nesse caso
# subestimaria o risco; um limiar de linhas sozinho não distingue 1M linhas
# estreitas (INTEGER) de 1M linhas largas (JSON). Cada critério cobre o
# ponto cego do outro.
#
# Valores confirmados por benchmark contra Postgres 16 e MariaDB 11 reais,
# medindo tempo/RSS dos dois lados de cada fronteira — ver
# `docs/system_design_doc.md` (seção "Streaming via cursor server-side")
# para a evidência completa.
_LIMIAR_LINHAS_STREAMING = 100_000
_LIMIAR_BYTES_STREAMING = 100_000_000

LARGURA_MEDIA_PADRAO_BYTES = 200
"""Fallback conservador (bytes/linha) quando o catálogo não tem estatística
de largura pra uma tabela — mesmo valor usado pelos dois Extratores, não
calibrado por motor específico."""


def deve_usar_streaming(total_linhas: int, largura_media_bytes: int) -> bool:
    """Decide se a tabela justifica o custo de manter uma transação aberta.

    Streaming via cursor server-side reduz o pico de memória client-side,
    mas mantém uma transação aberta pela duração da leitura — em Postgres,
    isso represa `VACUUM` no banco inteiro enquanto durar. Só compensa
    acima de um limiar de linhas OU de bytes estimados; tabelas pequenas
    seguem lidas com `fetchall()` direto.

    Args:
        total_linhas: total de linhas estimado da tabela (catálogo).
        largura_media_bytes: estimativa de largura média de linha.
    """
    tamanho_estimado_bytes = total_linhas * largura_media_bytes
    return (
        total_linhas > _LIMIAR_LINHAS_STREAMING
        or tamanho_estimado_bytes > _LIMIAR_BYTES_STREAMING
    )


def calcular_tamanho_lote(
    largura_media_bytes: int,
    teto_bytes: int = _TETO_BYTES_PADRAO,
    minimo: int = _MINIMO_PADRAO,
    maximo: int = _MAXIMO_PADRAO,
) -> int:
    """Converte largura média de linha (bytes) em nº de linhas por lote.

    Args:
        largura_media_bytes: estimativa de largura média de linha da
            tabela (`LARGURA_MEDIA_PADRAO_BYTES` como fallback de quem
            chama, quando o catálogo não tem estatística).
        teto_bytes: tamanho de lote alvo, em bytes.
        minimo: piso de linhas por lote, mesmo em tabela muito larga.
        maximo: teto de linhas por lote, mesmo em tabela muito estreita.
    """
    linhas_por_lote = teto_bytes // max(1, largura_media_bytes)
    return max(minimo, min(maximo, linhas_por_lote))


class _ColunaDescricao(Protocol):
    """1º item é o nome da coluna — psycopg2.Column e a tupla do pymysql cabem aqui."""

    def __getitem__(self, indice: int) -> object: ...


class _CursorComFetchmany(Protocol):
    """Cursor nomeado (Postgres) e SSCursor (MariaDB) satisfazem sem tipo comum."""

    @property
    def description(self) -> Sequence[_ColunaDescricao] | None: ...

    def fetchmany(self, size: int) -> list[tuple[object, ...]]: ...


def _diverge_alem_de_null(lotes: list[pl.DataFrame]) -> bool:
    """Indica se alguma coluna tem dtypes não-`Null` diferentes entre lotes.

    `Null` funde com qualquer tipo real sem risco — sintoma normal de um
    lote inteiro vindo de uma coluna nulável vazia. Qualquer outra
    divergência (ex.: `Int64` num lote, `Utf8` noutro) é uma anomalia: a
    mesma coluna da mesma query não deveria mudar de tipo entre lotes.
    """
    dtypes_por_coluna: dict[str, set[pl.DataType]] = defaultdict(set)
    for lote in lotes:
        for nome, dtype in lote.schema.items():
            if dtype != pl.Null:
                dtypes_por_coluna[nome].add(dtype)
    return any(len(dtypes) > 1 for dtypes in dtypes_por_coluna.values())


def concatenar_particoes(
    particoes: Sequence[pl.DataFrame],
    schema_se_vazio: Sequence[str] = (),
) -> pl.DataFrame:
    """Funde DataFrames de leituras independentes num único, preservando tudo.

    Duas origens de DataFrames independentes passam por aqui: os lotes de
    `fetchmany` de `ler_amostra_em_lotes` (mesma coluna, lidos em sequência)
    e as partições de uma leitura paralela intra-tabela (mesma coluna,
    lidas por faixa/bloco em conexões diferentes) — a fusão é idêntica nos
    dois casos, só muda de onde os DataFrames vêm.

    Cada DataFrame infere seu próprio dtype por coluna, isolado dos
    outros — um DataFrame inteiro `Null` numa coluna nulável (lote/faixa
    sem nenhum valor não-nulo) funde com qualquer tipo real sem risco; um
    DataFrame com valor real (`Int64` etc.) numa coluna que outro leu como
    `Null` quebraria `pl.concat` estrito por divergência de schema entre
    eles. A fusão só relaxa (`how="vertical_relaxed"`) quando a única
    divergência é `Null` contra um tipo real — qualquer outra divergência
    (ex.: `Int64` vs `Utf8`) propaga como erro explícito em vez de coagir
    silenciosamente entre tipos incompatíveis.

    Args:
        particoes: DataFrames a fundir, já com o mesmo conjunto de colunas
            entre si.
        schema_se_vazio: nomes de coluna a usar quando `particoes` está
            vazia (nada foi lido) — irrelevante quando `particoes` tem ao
            menos um DataFrame, já que cada um já carrega o próprio schema.
    """
    if not particoes:
        return pl.DataFrame(schema=list(schema_se_vazio))
    lista = list(particoes)
    if _diverge_alem_de_null(lista):
        return pl.concat(lista, how="vertical")
    return pl.concat(lista, how="vertical_relaxed")


def ler_amostra_em_lotes(
    cursor: _CursorComFetchmany,
    tamanho_lote: int,
) -> pl.DataFrame:
    """Lê um cursor já posicionado (query executada) em lotes de `fetchmany`.

    Nomes de coluna vêm de `cursor.description`, lido depois de cada
    `fetchmany` — não antes, como parâmetro. Cursor nomeado do psycopg2
    só popula `description` depois do 1º fetch (documentado no driver);
    ler antes disso devolve nomes vazios silenciosamente, sem erro —
    achado só contra Postgres real (testcontainers), não reproduzível com
    cursor mockado.

    A fusão dos lotes (`infer_schema_length=None` só olha as linhas de
    cada lote isoladamente) é feita por `concatenar_particoes` — ver ali
    o motivo de relaxar só divergência `Null` vs. tipo real.

    Args:
        cursor: cursor já com a query de amostra executada.
        tamanho_lote: nº de linhas lidas por chamada de `fetchmany`
            (tipicamente o resultado de `calcular_tamanho_lote`).
    """
    lotes: list[pl.DataFrame] = []
    nomes_colunas: list[str] = []
    while lote := cursor.fetchmany(tamanho_lote):
        if not nomes_colunas:
            nomes_colunas = [str(coluna[0]) for coluna in cursor.description or ()]
        lotes.append(
            pl.DataFrame(
                lote,
                schema=nomes_colunas,
                orient="row",
                infer_schema_length=None,
            )
        )
    if not nomes_colunas:
        nomes_colunas = [str(coluna[0]) for coluna in cursor.description or ()]
    return concatenar_particoes(lotes, schema_se_vazio=nomes_colunas)


class _CursorComFetchall(Protocol):
    """Cursor comum dos dois drivers — usado no caminho não-streaming."""

    @property
    def description(self) -> Sequence[_ColunaDescricao] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


def ler_amostra_fetchall(cursor: _CursorComFetchall) -> pl.DataFrame:
    """Lê um cursor já posicionado (query executada) de uma vez, via `fetchall`.

    Caminho não-streaming: tabela pequena o bastante para materializar o
    resultset inteiro sem risco relevante de pico de memória.

    Args:
        cursor: cursor já com a query de amostra executada.
    """
    nomes_colunas = [str(coluna[0]) for coluna in cursor.description or ()]
    linhas = cursor.fetchall()
    if not linhas:
        return pl.DataFrame(schema=nomes_colunas)
    return pl.DataFrame(
        linhas, schema=nomes_colunas, orient="row", infer_schema_length=None
    )

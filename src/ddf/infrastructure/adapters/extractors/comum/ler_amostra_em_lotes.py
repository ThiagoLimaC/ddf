"""Lê um cursor de streaming em lotes, sem materializar o resultset inteiro."""

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

# Candidatos iniciais, calibrados pelo benchmark da issue #114 — não valores
# finais. Dois critérios (linhas OU bytes) em vez de um só: um limiar de
# bytes sozinho depende da estimativa de largura média, que cai num
# fallback conservador quando a tabela nunca foi analisada — nesse caso
# subestimaria o risco; um limiar de linhas sozinho não distingue 1M linhas
# estreitas (INTEGER) de 1M linhas largas (JSON). Cada critério cobre o
# ponto cego do outro.
_LIMIAR_LINHAS_STREAMING = 100_000
_LIMIAR_BYTES_STREAMING = 100_000_000


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


class _CursorComFetchmany(Protocol):
    """Cursor nomeado (Postgres) e SSCursor (MariaDB) satisfazem sem tipo comum."""

    def fetchmany(self, size: int) -> list[tuple[object, ...]]: ...


def ler_amostra_em_lotes(
    cursor: _CursorComFetchmany,
    nomes_colunas: list[str],
    tamanho_lote: int,
) -> pl.DataFrame:
    """Lê um cursor já posicionado (query executada) em lotes de `fetchmany`.

    Args:
        cursor: cursor já com a query de amostra executada.
        nomes_colunas: nomes das colunas retornadas, na ordem do SELECT.
        tamanho_lote: nº de linhas lidas por chamada de `fetchmany`
            (tipicamente o resultado de `calcular_tamanho_lote`).
    """
    lotes: list[pl.DataFrame] = []
    while lote := cursor.fetchmany(tamanho_lote):
        lotes.append(
            pl.DataFrame(
                lote,
                schema=nomes_colunas,
                orient="row",
                infer_schema_length=None,
            )
        )
    if not lotes:
        return pl.DataFrame(schema=nomes_colunas)
    return pl.concat(lotes)

"""Construção de ColunaExtraida a partir de metadados de catálogo do Postgres."""

from typing import NamedTuple

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.extraction import ColunaExtraida
from ddf.infrastructure.adapters.extractors.postgres.mapeamento_de_tipos import (
    mapear_tipo_postgres,
)


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SCHEMA_SQL (a partir da 2ª coluna — a 1ª é table_name, usada só
    para agrupar por tabela antes de construir esta tupla) — construir a
    tupla é o único ponto onde essa correspondência posicional existe; daqui
    pra frente, todo o código lê por nome (`linha.udt_name`), não por índice.
    """

    nome: str
    udt_name: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None
    is_nullable: str


class _MetadadosDoSchema(NamedTuple):
    """Metadados de catálogo de todas as tabelas de um schema, lidos de uma vez.

    Populado por ExtratorPostgres._obter_metadados_schema e cacheado por
    schema — elimina o N+1 de rodar 4 queries de metadado por tabela restrita.
    fks_por_tabela guarda linhas cruas com `constraint_name` como 5º campo
    — não faz parte do formato que construir_colunas_fk espera;
    extrair_tabela descarta esse campo antes de repassar —, não
    ReferenciaDeColuna já resolvida — a resolução por coluna (com Aviso de
    colisão) continua acontecendo por tabela, em extrair_tabela, não aqui.
    restricoes_fk_compostas_por_tabela já vem agrupado por constraint
    (construir_restricoes_fk_compostas), mesmo padrão de
    restricoes_unicas_por_tabela.
    """

    colunas_por_tabela: dict[str, list[_LinhaColuna]]
    pks_por_tabela: dict[str, set[str]]
    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]]
    unicas_por_tabela: dict[str, set[str]]
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]]
    restricoes_fk_compostas_por_tabela: dict[str, list[RestricaoDeFkComposta]]
    total_linhas_por_tabela: dict[str, int]


def _construir_coluna(
    linha: _LinhaColuna,
    colunas_pk: set[str],
    colunas_fk: dict[str, list[ReferenciaDeColuna]],
    colunas_unicas: set[str],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK/UNIQUE já lidas."""
    referencias = colunas_fk.get(linha.nome, [])
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=mapear_tipo_postgres(
            linha.udt_name,
            linha.tamanho_maximo,
            linha.precisao,
            linha.escala,
        ),
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=bool(referencias),
        referencias=referencias,
        nao_nulavel=linha.is_nullable == "NO",
        unica=linha.nome in colunas_unicas,
    )

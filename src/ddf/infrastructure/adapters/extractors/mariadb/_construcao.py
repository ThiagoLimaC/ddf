"""Construção de ColunaExtraida e agrupamento de metadados de catálogo do MariaDB."""

from collections import defaultdict
from typing import NamedTuple

import polars as pl

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida
from ddf.infrastructure.adapters.extractors.mariadb.mapeamento_de_tipos import (
    _extrair_coluna_json_valid,
    mapear_tipo_mariadb,
)


class _LinhaColuna(NamedTuple):
    """Uma linha de information_schema.columns, nomeada por campo.

    A ordem dos campos aqui precisa acompanhar a ordem do SELECT em
    _COLUNAS_SQL (a partir da 2ª coluna — a 1ª é table_name, usada só para
    agrupar por tabela antes de construir esta tupla) — construir a tupla
    é o único ponto onde essa correspondência posicional existe; daqui pra
    frente, todo o código lê por nome (`linha.data_type`), não por índice.
    """

    nome: str
    data_type: str
    column_type: str
    tamanho_maximo: int | None
    precisao: int | None
    escala: int | None
    is_nullable: str


class _MetadadosDoSchema(NamedTuple):
    """Metadados de catálogo de todas as tabelas de um escopo, lidos de uma vez.

    Populado por ExtratorMariaDB._obter_metadados_schema e cacheado por
    escopo — elimina o N+1 de rodar 6 queries de metadado por tabela
    restrita. restricoes_fk_compostas_por_tabela é pré-computado aqui,
    mesmo padrão do _MetadadosDoSchema equivalente do ExtratorPostgres —
    construir_restricoes_fk_compostas é função pura de CPU, não bate no
    banco, então pré-computar não adiciona round-trip.
    """

    colunas_por_tabela: dict[str, list[_LinhaColuna]]
    pks_por_tabela: dict[str, set[str]]
    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]]
    unicas_por_tabela: dict[str, set[str]]
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]]
    restricoes_fk_compostas_por_tabela: dict[str, list[RestricaoDeFkComposta]]
    colunas_json_por_tabela: dict[str, set[str]]
    total_linhas_por_tabela: dict[str, int]
    largura_media_por_tabela: dict[str, int]


def _quotar_identificador(nome: str) -> str:
    """Escapa um identificador (schema/tabela) pra uso seguro em SQL cru.

    pymysql não tem um equivalente ao psycopg2.sql.Identifier — crase
    duplicada (` `` `) é a forma do MariaDB de escapar uma crase literal
    dentro de um identificador entre crases.
    """
    return f"`{nome.replace('`', '``')}`"


def _construir_coluna(
    linha: _LinhaColuna,
    colunas_pk: set[str],
    colunas_fk: dict[str, list[ReferenciaDeColuna]],
    colunas_unicas: set[str],
    colunas_json: set[str],
) -> ColunaExtraida:
    """Combina uma linha de information_schema.columns com PK/FK/UNIQUE/JSON já lidas.

    `colunas_json` sobrescreve o resultado de `mapear_tipo_mariadb` — o
    MariaDB nunca reporta `data_type == "json"` de verdade (ver
    `_extrair_coluna_json_valid`), então a única forma de saber que uma
    coluna `LONGTEXT` é na real uma coluna `JSON` é via essa reclassificação
    baseada no `CHECK_CLAUSE`, não via `data_type`.
    """
    referencias = colunas_fk.get(linha.nome, [])
    tipo_dado = (
        TipoDeDado(categoria=CategoriaDeDado.JSON)
        if linha.nome in colunas_json
        else mapear_tipo_mariadb(
            linha.data_type,
            linha.column_type,
            linha.tamanho_maximo,
            linha.precisao,
            linha.escala,
        )
    )
    return ColunaExtraida(
        nome=linha.nome,
        tipo_dado=tipo_dado,
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=bool(referencias),
        referencias=referencias,
        nao_nulavel=linha.is_nullable == "NO",
        unica=linha.nome in colunas_unicas,
    )


def _particionar_colunas_unicas(
    linhas: list[tuple[str, str]],
) -> tuple[set[str], list[RestricaoUnica]]:
    """Agrupa (constraint_name, column_name) por constraint e particiona por tamanho.

    Constraint com 1 coluna vira `unica` single-column; com 2+ colunas vira
    uma `RestricaoUnica` composta. Assume que `linhas` já pertence a uma
    única tabela — quem chama (`_agrupar_colunas_unicas_por_tabela`)
    garante isso agrupando por `table_name` antes.

    Args:
        linhas: pares (constraint_name, column_name) de uma única tabela,
            já ordenados por `(constraint_name, ordinal_position)` pela
            query, preservando a ordem real das colunas dentro da
            constraint.

    Returns:
        Tupla (nomes de coluna únicas single-column, lista de RestricaoUnica
        para as constraints compostas).
    """
    colunas_por_constraint: dict[str, list[str]] = {}
    for nome_constraint, nome_coluna in linhas:
        colunas_por_constraint.setdefault(nome_constraint, []).append(nome_coluna)

    unicas: set[str] = set()
    restricoes_unicas: list[RestricaoUnica] = []
    for colunas in colunas_por_constraint.values():
        if len(colunas) == 1:
            unicas.add(colunas[0])
        else:
            restricoes_unicas.append(RestricaoUnica(colunas=tuple(colunas)))
    return unicas, restricoes_unicas


def _agrupar_colunas_unicas_por_tabela(
    linhas: list[tuple[str, str, str]],
) -> tuple[dict[str, set[str]], dict[str, list[RestricaoUnica]]]:
    """Separa por tabela antes de particionar — constraint só é única por tabela.

    `_COLUNAS_UNICAS_SQL` já cruza `table_name` no JOIN (não só no WHERE),
    então linhas de tabelas diferentes nunca se misturam ali; mas duas
    tabelas do mesmo escopo podem usar o mesmo `constraint_name` (ex.:
    `UNIQUE(email)` gerando "email" em ambas) — sem separar por tabela
    antes de chamar `_particionar_colunas_unicas`, os grupos colidiriam
    entre tabelas.

    Args:
        linhas: (table_name, constraint_name, column_name) de todo o
            escopo.

    Returns:
        (unicas_por_tabela, restricoes_unicas_por_tabela).
    """
    linhas_por_tabela: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for nome_tabela, nome_constraint, nome_coluna in linhas:
        linhas_por_tabela[nome_tabela].append((nome_constraint, nome_coluna))

    unicas_por_tabela: dict[str, set[str]] = {}
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]] = {}
    for nome_tabela, linhas_da_tabela in linhas_por_tabela.items():
        unicas, restricoes = _particionar_colunas_unicas(linhas_da_tabela)
        unicas_por_tabela[nome_tabela] = unicas
        restricoes_unicas_por_tabela[nome_tabela] = restricoes
    return unicas_por_tabela, restricoes_unicas_por_tabela


def _colunas_json_de_check_clauses(
    check_clauses: list[str], nomes_colunas_reais: set[str]
) -> set[str]:
    """Extrai as colunas JSON reais a partir dos CHECK_CLAUSE de uma tabela.

    O cruzamento com `nomes_colunas_reais` (as colunas de fato lidas de
    `information_schema.columns` para esta tabela) é defesa em profundidade
    contra CHECK_CLAUSE que não segue o padrão `json_valid(...)`.

    Args:
        check_clauses: valores de CHECK_CLAUSE de uma única tabela, já
            separados por `_agrupar_colunas_json_por_tabela`.
        nomes_colunas_reais: nomes de todas as colunas desta tabela, lidas
            de _COLUNAS_SQL.

    Returns:
        Nomes de coluna desta tabela que são JSON de verdade.
    """
    colunas_json: set[str] = set()
    for check_clause in check_clauses:
        nome_coluna = _extrair_coluna_json_valid(check_clause)
        if nome_coluna is not None and nome_coluna in nomes_colunas_reais:
            colunas_json.add(nome_coluna)
    return colunas_json


def _agrupar_colunas_json_por_tabela(
    linhas: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Agrupa (table_name, check_clause) de todo o escopo por tabela.

    `information_schema.check_constraints` traz `table_name` nativamente —
    diferente de UNIQUE, aqui não há JOIN nenhum pra cruzar, só agrupamento
    direto pela coluna que a própria view já expõe.

    Args:
        linhas: (table_name, check_clause) de todo o escopo.

    Returns:
        check_clauses agrupados por table_name.
    """
    check_clauses_por_tabela: dict[str, list[str]] = defaultdict(list)
    for nome_tabela, check_clause in linhas:
        check_clauses_por_tabela[nome_tabela].append(check_clause)
    return dict(check_clauses_por_tabela)


_TIPOS_INTEIROS_ELEGIVEIS_PARA_FAIXA = frozenset(
    {"tinyint", "smallint", "mediumint", "int", "bigint"}
)


class _PkElegivel(NamedTuple):
    """PK de coluna única e tipo inteiro — elegível para amostragem por faixa."""

    nome_coluna: str


class _PkNaoElegivel(NamedTuple):
    """PK não elegível para amostragem por faixa — motivo do fallback."""

    motivo: str


def _elegibilidade_de_pk_para_faixa(
    colunas_pk: set[str],
    linhas_colunas: list[_LinhaColuna],
) -> _PkElegivel | _PkNaoElegivel:
    """Decide se a PK da tabela serve para amostragem por faixa (RequisicaoPorFaixa).

    Elegível só com PK de coluna única e tipo inteiro (tinyint/smallint/
    mediumint/int/bigint, antes de qualquer promoção INTEGER→BOOLEAN pela
    amostra — essa promoção nunca se aplica à PK na prática, mas a checagem
    aqui usa o `data_type` cru do catálogo, não a categoria final) — os
    únicos tipos onde `MAX(pk)` e um corte `pk >= valor` fazem sentido
    aritmético. PK composta, ausente, ou de outro tipo (UUID, VARCHAR,
    DATE...) não serve — quem chama cai para o mecanismo probabilístico
    padrão, com `Aviso` explicando o motivo.
    """
    if len(colunas_pk) == 0:
        return _PkNaoElegivel(motivo="tabela sem chave primária")
    if len(colunas_pk) > 1:
        return _PkNaoElegivel(motivo="chave primária composta")
    (nome_pk,) = colunas_pk
    linha_pk = next((linha for linha in linhas_colunas if linha.nome == nome_pk), None)
    tipo_e_elegivel = (
        linha_pk is not None
        and linha_pk.data_type in _TIPOS_INTEIROS_ELEGIVEIS_PARA_FAIXA
    )
    if not tipo_e_elegivel:
        return _PkNaoElegivel(
            motivo=f"chave primária '{nome_pk}' não é de tipo inteiro"
        )
    return _PkElegivel(nome_coluna=nome_pk)


def _promover_booleanos_pela_amostra(
    colunas: list[ColunaExtraida],
    amostra: pl.DataFrame,
    candidatos_booleanos: set[str],
) -> list[ColunaExtraida]:
    """Promove INTEGER→BOOLEAN pra colunas tinyint(1) cuja amostra é só 0/1.

    MariaDB não guarda em lugar nenhum a distinção BOOLEAN vs TINYINT(1) —
    é decidido aqui, com base em dado real da própria extração, não em
    convenção de nome de coluna. Amostra vazia ou só nulos não promove:
    falta de evidência não é evidência de booleano.
    """
    colunas_promovidas: list[ColunaExtraida] = []
    for coluna in colunas:
        if coluna.nome in candidatos_booleanos and coluna.nome in amostra.columns:
            valores = amostra[coluna.nome].drop_nulls()
            if valores.len() > 0 and bool(valores.is_in([0, 1]).all()):
                coluna = coluna.model_copy(
                    update={"tipo_dado": TipoDeDado(categoria=CategoriaDeDado.BOOLEAN)}
                )
        colunas_promovidas.append(coluna)
    return colunas_promovidas

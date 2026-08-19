"""Construção de ColunaExtraida a partir de metadados de catálogo do Postgres."""

from collections import defaultdict
from typing import Any, NamedTuple, assert_never

from psycopg2 import sql
from psycopg2.extensions import connection as conexao_postgres

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoDeAmostragem,
    RequisicaoPorFaixa,
)
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.extraction import ColunaExtraida
from ddf.infrastructure.adapters.outbounds.extractors.comum.construir_restricoes_fk_compostas import (  # noqa: E501
    construir_restricoes_fk_compostas,
)
from ddf.infrastructure.adapters.outbounds.extractors.comum.ler_amostra_em_lotes import (
    LARGURA_MEDIA_PADRAO_BYTES,
)
from ddf.infrastructure.adapters.outbounds.extractors.comum.seed_efetivo import (
    seed_efetivo,
)
from ddf.infrastructure.adapters.outbounds.extractors.postgres.mapeamento_de_tipos import (
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
    precisao_fracionaria: int | None
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
    restricoes_unicas_por_tabela. tabelas_com_coluna_comprimivel vem de
    `pg_attribute.attstorage` (catálogo real, não uma lista fixa de nomes
    de tipo) — cobre qualquer tipo sujeito a compressão TOAST, incluindo
    arrays, domains sobre `text` e extensões (`citext`/`hstore`/
    `tsvector`), que uma lista de `udt_name` hardcoded deixaria escapar.
    filhos_por_tabela_mae mapeia tabela-mãe particionada → suas partições
    reais do mesmo schema (via `pg_inherits`) — usado só para agregar
    `total_linhas_por_tabela` da mãe a partir da soma das filhas.
    """

    colunas_por_tabela: dict[str, list[_LinhaColuna]]
    pks_por_tabela: dict[str, set[str]]
    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]]
    unicas_por_tabela: dict[str, set[str]]
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]]
    restricoes_fk_compostas_por_tabela: dict[str, list[RestricaoDeFkComposta]]
    total_linhas_por_tabela: dict[str, int]
    largura_media_por_tabela: dict[str, int]
    tabelas_com_coluna_comprimivel: frozenset[str]
    tabelas_particionadas: frozenset[str]
    filhos_por_tabela_mae: dict[str, list[str]]


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
            linha.precisao_fracionaria,
        ),
        chave_primaria=linha.nome in colunas_pk,
        chave_estrangeira=bool(referencias),
        referencias=referencias,
        nao_nulavel=linha.is_nullable == "NO",
        unica=linha.nome in colunas_unicas,
    )


def particoes_de_blocos(total_blocos: int, n: int) -> list[tuple[int, int | None]]:
    """Divide `[0, total_blocos)` em `n` faixas contíguas de blocos `ctid`.

    Determinístico, disjunto e exaustivo — cada bloco cai em exatamente uma
    faixa. A última faixa não tem teto (`None`, sem `AND ctid < ...`): o
    total de blocos foi lido antes da leitura de verdade começar, então um
    teto fechado excluiria silenciosamente blocos adicionados à tabela
    nesse meio-tempo — de forma assimétrica em relação a uma leitura
    sequencial simples, que sempre vê o estado mais recente até onde
    conseguir ler.

    Args:
        total_blocos: total de blocos de 8KB da tabela (via
            `pg_relation_size`/`block_size`).
        n: número de faixas a gerar — tipicamente o nº de conexões
            reservadas para a leitura paralela.

    Returns:
        Lista de `n` tuplas `(inicio_inclusive, fim_exclusivo | None)`.
    """
    if n <= 0:
        return []
    tamanho_faixa = max(1, total_blocos // n)
    faixas: list[tuple[int, int | None]] = []
    inicio = 0
    for indice in range(n):
        if indice == n - 1:
            faixas.append((inicio, None))
        else:
            fim = inicio + tamanho_faixa
            faixas.append((inicio, fim))
            inicio = fim
    return faixas


def montar_metadados_do_schema(
    linhas_colunas: list[tuple[Any, ...]],
    linhas_pks: list[tuple[Any, ...]],
    linhas_fks: list[tuple[Any, ...]],
    linhas_unicas: list[tuple[Any, ...]],
    linhas_total_linhas: list[tuple[Any, ...]],
    linhas_largura_media: list[tuple[Any, ...]],
    linhas_comprimiveis: list[tuple[Any, ...]],
    linhas_particionadas: list[tuple[Any, ...]],
    linhas_filhos_de_particao: list[tuple[Any, ...]],
) -> _MetadadosDoSchema:
    """Agrupa as 9 linhas cruas de `cursor.fetchall()` em `_MetadadosDoSchema`.

    Cada parâmetro `linhas_*` é a saída bruta de uma das 9 queries de
    `_obter_metadados_schema`, na ordem em que são executadas — esta função
    só agrupa por tabela e monta os `dict`/`frozenset` finais, sem tocar
    conexão/cursor. `linhas_unicas` guarda `(nome_tabela, indexrelid,
    nome_coluna)`: um índice único pode cobrir mais de uma coluna, por isso
    o agrupamento intermediário por `indexrelid` antes de decidir se vira
    `unicas_por_tabela` (1 coluna) ou `restricoes_unicas_por_tabela` (2+).
    `linhas_filhos_de_particao` guarda `(tabela_mae, tabela_filha)`: depois
    de montar `total_linhas_por_tabela` normalmente (cada filha com sua
    própria estimativa), a entrada da mãe é sobrescrita pela soma real das
    filhas — a estimativa própria da mãe é sempre ~0 (autovacuum nunca
    analisa `relkind='p'` automaticamente). A agregação repete até nenhum
    valor mudar (ponto fixo), não um único passe: em particionamento de 2+
    níveis (ex. partição por ano → sub-partição por mês), `pg_inherits`
    devolve as linhas na ordem pai-antes-do-filho — um único passe bottom-up
    processaria a raiz antes da sub-partição intermediária já ter sido
    agregada, deixando a raiz com o valor bruto (~0) dessa intermediária.
    """
    colunas_por_tabela: dict[str, list[_LinhaColuna]] = defaultdict(list)
    for linha_bruta in linhas_colunas:
        nome_tabela, *resto_colunas = linha_bruta
        colunas_por_tabela[nome_tabela].append(_LinhaColuna(*resto_colunas))

    pks_por_tabela: dict[str, set[str]] = defaultdict(set)
    for nome_tabela, nome_coluna_pk in linhas_pks:
        pks_por_tabela[nome_tabela].add(nome_coluna_pk)

    fks_por_tabela: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)
    for linha_fk in linhas_fks:
        nome_tabela, *resto_fk = linha_fk
        fks_por_tabela[nome_tabela].append(tuple(resto_fk))

    restricoes_fk_compostas_por_tabela: dict[str, list[RestricaoDeFkComposta]] = {
        nome_tabela: construir_restricoes_fk_compostas(linhas)
        for nome_tabela, linhas in fks_por_tabela.items()
    }

    grupos_unicos: dict[str, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for nome_tabela, indexrelid, nome_coluna in linhas_unicas:
        grupos_unicos[nome_tabela][indexrelid].append(nome_coluna)

    unicas_por_tabela: dict[str, set[str]] = defaultdict(set)
    restricoes_unicas_por_tabela: dict[str, list[RestricaoUnica]] = defaultdict(list)
    for nome_tabela, indices in grupos_unicos.items():
        for colunas_do_indice in indices.values():
            if len(colunas_do_indice) == 1:
                unicas_por_tabela[nome_tabela].add(colunas_do_indice[0])
            else:
                restricoes_unicas_por_tabela[nome_tabela].append(
                    RestricaoUnica(colunas=tuple(colunas_do_indice))
                )

    total_linhas_por_tabela: dict[str, int] = {}
    for nome_tabela, linhas_estimadas in linhas_total_linhas:
        total_linhas_por_tabela[nome_tabela] = max(0, round(linhas_estimadas))

    largura_media_por_tabela: dict[str, int] = {}
    for nome_tabela, soma_avg_width in linhas_largura_media:
        largura_media_por_tabela[nome_tabela] = (
            int(soma_avg_width) if soma_avg_width else LARGURA_MEDIA_PADRAO_BYTES
        )

    tabelas_com_coluna_comprimivel = frozenset(
        nome_tabela for (nome_tabela,) in linhas_comprimiveis
    )
    tabelas_particionadas = frozenset(
        nome_tabela for (nome_tabela,) in linhas_particionadas
    )

    filhos_por_tabela_mae: dict[str, list[str]] = defaultdict(list)
    for tabela_mae, tabela_filha in linhas_filhos_de_particao:
        filhos_por_tabela_mae[tabela_mae].append(tabela_filha)
    alterou = True
    while alterou:
        alterou = False
        for tabela_mae, filhas in filhos_por_tabela_mae.items():
            nova_soma = sum(total_linhas_por_tabela.get(filha, 0) for filha in filhas)
            if total_linhas_por_tabela.get(tabela_mae) != nova_soma:
                total_linhas_por_tabela[tabela_mae] = nova_soma
                alterou = True

    return _MetadadosDoSchema(
        colunas_por_tabela=dict(colunas_por_tabela),
        pks_por_tabela=dict(pks_por_tabela),
        fks_por_tabela=dict(fks_por_tabela),
        unicas_por_tabela=dict(unicas_por_tabela),
        restricoes_unicas_por_tabela=dict(restricoes_unicas_por_tabela),
        restricoes_fk_compostas_por_tabela=restricoes_fk_compostas_por_tabela,
        total_linhas_por_tabela=total_linhas_por_tabela,
        largura_media_por_tabela=largura_media_por_tabela,
        tabelas_com_coluna_comprimivel=tabelas_com_coluna_comprimivel,
        tabelas_particionadas=tabelas_particionadas,
        filhos_por_tabela_mae=dict(filhos_por_tabela_mae),
    )


def montar_consulta_amostra(
    schema: str, tabela: str, requisicao: RequisicaoDeAmostragem
) -> tuple[sql.Composed, RequisicaoDeAmostragem]:
    """Monta a query `SELECT` de amostra pro dialeto Postgres, por estratégia.

    `requisicao_efetiva` (2º item da tupla) é a mesma requisição recebida,
    exceto pra `AmostragemProbabilistica`/`RequisicaoPorFaixa` sem `seed`
    explícito: `seed_efetivo` preenche com o default e ele precisa ser
    devolvido pra `extrair_tabela` registrar o seed realmente usado nos
    metadados da amostra (reprodutibilidade), não só na query executada.
    """
    requisicao_efetiva: RequisicaoDeAmostragem
    consulta: sql.Composed
    match requisicao:
        case AmostragemProbabilistica(percentual=percentual, seed=seed):
            seed_usado = seed_efetivo(seed)
            requisicao_efetiva = AmostragemProbabilistica(
                percentual=percentual, seed=seed_usado
            )
            consulta = sql.SQL(
                "SELECT * FROM {}.{} TABLESAMPLE BERNOULLI ({}) REPEATABLE ({})"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(tabela),
                sql.Literal(percentual),
                sql.Literal(seed_usado),
            )
        case AmostragemIntegral():
            requisicao_efetiva = requisicao
            consulta = sql.SQL("SELECT * FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(tabela)
            )
        case RequisicaoPorFaixa(percentual=percentual, seed=seed):
            seed_usado = seed_efetivo(seed)
            requisicao_efetiva = RequisicaoPorFaixa(
                percentual=percentual, seed=seed_usado
            )
            consulta = sql.SQL(
                "SELECT * FROM {}.{} TABLESAMPLE SYSTEM ({}) REPEATABLE ({})"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(tabela),
                sql.Literal(percentual),
                sql.Literal(seed_usado),
            )
        case _ as nunca:
            assert_never(nunca)
    return consulta, requisicao_efetiva


def query_particao_ctid(
    conexao: conexao_postgres,
    schema: str,
    tabela: str,
    inicio: int,
    fim: int | None,
) -> str:
    """Monta o texto SQL de uma faixa de `ctid`, com quoting seguro.

    `connectorx` recebe uma lista de strings SQL prontas (modo de
    particionamento manual), não um cursor — por isso a query é renderizada
    aqui via `sql.Composed.as_string`, em vez de executada diretamente.
    `conexao` não é state do Extrator: é só o contexto de quoting que
    `as_string` exige (encoding/tipo de escape do driver).
    """
    condicao = sql.SQL("ctid >= {}::tid").format(sql.Literal(f"({inicio},0)"))
    if fim is not None:
        condicao = sql.SQL("{} AND ctid < {}::tid").format(
            condicao, sql.Literal(f"({fim},0)")
        )
    consulta = sql.SQL("SELECT * FROM {}.{} WHERE {}").format(
        sql.Identifier(schema), sql.Identifier(tabela), condicao
    )
    return consulta.as_string(conexao)

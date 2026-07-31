"""GeradorDbt: projeto dbt standalone (staging layer) a partir do BancoAnalisado.

Única saída do sistema cujos identificadores no artefato (nomes de coluna/
tabela em `schema.yml`, `sources.yml` e no SQL, além do vocabulário de teste
`unique`/`not_null`/`relationships`/`accepted_values`) ficam em inglês — é o
contrato real consumido pelo dbt e pelo warehouse, não uma escolha de estilo
do código Python (ver `docs/engineer_guidelines.md`, "Nomenclatura: idioma
como contrato").
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    TabelaAnalisada,
    TipoDeMetrica,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators._metricas import _elegivel_para_enumeracao

_ORIGEM = "GeradorDbt"

_DBT_PROJECT: dict[str, Any] = {
    "name": "ddf_staging",
    "version": "1.0.0",
    "config-version": 2,
    "profile": "ddf_staging",
    "model-paths": ["models"],
    "models": {
        "ddf_staging": {
            "staging": {"+materialized": "view"},
        },
    },
}

_PACKAGES_YML: dict[str, Any] = {
    "packages": [
        {"package": "dbt-labs/dbt_utils", "version": [">=1.0.0", "<2.0.0"]},
    ],
}

_CATEGORIAS_COM_TIMEZONE = {CategoriaDeDado.TIMESTAMP, CategoriaDeDado.TIME}
_CATEGORIAS_SEM_EQUIVALENTE_ANSI = {CategoriaDeDado.ENUM, CategoriaDeDado.SET}

# Testes "soft" (issue #90) — thresholds fixos, não configuráveis nesta v1.
# Mais afastados da fronteira (10%/95%, não 5%/90%) de propósito: perto do
# piso de amostra (_TAMANHO_AMOSTRA_MINIMO_SOFT), o erro padrão de uma
# proporção é da mesma ordem de um threshold mais apertado — a sugestão
# "piscaria" entre reextrações por ruído amostral, não mudança real de dado.
_LIMITE_NULO_SOFT = 10.0
_LIMITE_UNICO_SOFT = 95.0
_TAMANHO_AMOSTRA_MINIMO_SOFT = 100

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_ambiente = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 — saída é SQL/Markdown, não HTML
)
_TEMPLATE_SQL = _ambiente.get_template("stg_tabela.sql.jinja2")
_TEMPLATE_README = _ambiente.get_template("readme.md.jinja2")

# Macros dbt (issue #90): conteúdo estático, lido direto do disco — não
# passam pelo _ambiente acima porque `{% test %}`/`{% macro %}` são tags que
# só o dbt-core (em runtime do dbt, no ambiente do usuário) sabe interpretar;
# o Environment deste projeto não tem essa extensão e falharia ao parsear.
_ARQUIVOS_MATCHES_FORMAT = (
    "matches_format.sql",
    "postgres__validate_format.sql",
    "mariadb__validate_format.sql",
)
_CONTEUDO_MATCHES_FORMAT: dict[str, str] = {
    nome: (_TEMPLATES_DIR / "macros" / "matches_format" / nome).read_text()
    for nome in _ARQUIVOS_MATCHES_FORMAT
}
_CONTEUDO_UNIQUE_PERCENTAGE_AT_LEAST = (
    _TEMPLATES_DIR / "macros" / "unique_percentage_at_least.sql"
).read_text()
_CONTEUDO_COMPOSITE_RELATIONSHIPS = (
    _TEMPLATES_DIR / "macros" / "composite_relationships.sql"
).read_text()


def _nome_model(escopo: str, tabela: str) -> str:
    """Nome do staging model: `stg_<escopo>__<tabela>` (convenção dbt multi-source).

    Única fonte da convenção de nomenclatura — usada tanto para o model que
    a própria tabela gera quanto para o `ref()` de uma FK que aponta para
    outra tabela do lote, evitando duas formatações divergentes do mesmo
    nome.

    Args:
        escopo: `nome_escopo` da tabela.
        tabela: `nome_tabela` da tabela.

    Returns:
        Nome do model, único mesmo quando dois escopos têm tabela de mesmo
        nome — `stg_<tabela>` sozinho colidiria nesse caso.
    """
    return f"stg_{escopo}__{tabela}"


def _tipo_sql(tipo: TipoDeDado) -> str:
    """Mapeia TipoDeDado para o tipo SQL ANSI-ish usado no CAST.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        Tipo SQL com atributos de precisão, ex.: `NUMERIC(10,2)`,
        `VARCHAR(255)`, `TIMESTAMP WITH TIME ZONE`. ENUM/SET (sem
        equivalente ANSI portável) caem para `VARCHAR`.
    """
    categoria = tipo.categoria

    if categoria == CategoriaDeDado.VARCHAR:
        return f"VARCHAR({tipo.tamanho_maximo})" if tipo.tamanho_maximo else "VARCHAR"
    if categoria == CategoriaDeDado.CHAR:
        return f"CHAR({tipo.tamanho_fixo})" if tipo.tamanho_fixo else "CHAR"
    if categoria == CategoriaDeDado.NUMERIC:
        if tipo.precisao is not None:
            return f"NUMERIC({tipo.precisao},{tipo.escala or 0})"
        return "NUMERIC"
    if categoria == CategoriaDeDado.FLOAT:
        return "DOUBLE PRECISION" if tipo.com_precisao_dupla else "REAL"
    if categoria in _CATEGORIAS_COM_TIMEZONE and tipo.com_timezone:
        return f"{categoria.value} WITH TIME ZONE"
    if categoria in _CATEGORIAS_SEM_EQUIVALENTE_ANSI:
        return "VARCHAR"
    if categoria == CategoriaDeDado.ARRAY and tipo.elemento is not None:
        return f"{_tipo_sql(TipoDeDado(categoria=tipo.elemento))}[]"

    return str(categoria.value)


def _tem_cast_seguro(tipo: TipoDeDado) -> bool:
    """Decide se `tipo` tem um CAST SQL seguro a fazer.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        False para UNKNOWN (sem tipo mapeado) e para ARRAY sem elemento
        reconhecido (`[]` sem tipo dentro não é SQL válido) — nesses casos
        a coluna é projetada raw. True para as demais categorias.
    """
    if tipo.categoria == CategoriaDeDado.UNKNOWN:
        return False
    return tipo.categoria != CategoriaDeDado.ARRAY or tipo.elemento is not None


def _expressao_coluna(coluna: ColunaAnalisada) -> str:
    """Monta a expressão SELECT de uma coluna: CAST explícito ou passthrough.

    Args:
        coluna: coluna analisada a projetar no SELECT.

    Returns:
        `CAST(<coluna> AS <tipo>)`, ou o nome puro da coluna quando não há
        CAST seguro a fazer (ver `_tem_cast_seguro`).
    """
    if not _tem_cast_seguro(coluna.tipo_dado):
        return coluna.nome
    return f"CAST({coluna.nome} AS {_tipo_sql(coluna.tipo_dado)})"


def _renderizar_sql(tabela: TabelaAnalisada) -> str:
    """Renderiza o SELECT com CAST + alias por coluna do staging model.

    Args:
        tabela: tabela analisada a projetar.

    Returns:
        SQL do staging model, lendo de `{{ source(escopo, tabela) }}`.
    """
    total = len(tabela.colunas)
    colunas = [
        {
            "expressao": _expressao_coluna(coluna),
            "nome": coluna.nome,
            "sufixo": "," if indice < total - 1 else "",
        }
        for indice, coluna in enumerate(tabela.colunas)
    ]
    origem = "{{ source('" + tabela.nome_escopo + "', '" + tabela.nome_tabela + "') }}"
    return _TEMPLATE_SQL.render(colunas=colunas, origem=origem)


def _metrica_de_coluna(coluna: ColunaAnalisada) -> MetricasBaseColuna | None:
    """Filtra a MetricasBaseColuna de uma coluna, se ela já tiver sido calculada.

    Args:
        coluna: coluna analisada.

    Returns:
        A MetricasBaseColuna encontrada, ou None se ausente.
    """
    metricas = [m for m in coluna.metricas if isinstance(m, MetricasBaseColuna)]
    return metricas[0] if metricas else None


def _precisa_teste_soft_nulo(
    coluna: ColunaAnalisada, metrica: MetricasBaseColuna | None, tamanho_amostra: int
) -> bool:
    """Decide se a coluna cai na faixa "nulo baixo mas não-zero" (issue #90).

    Mutuamente exclusivo com o `not_null` hard por construção: hard cobre
    `percentual_nulo == 0.0` ou `coluna.nao_nulavel`; aqui a faixa exige
    `percentual_nulo > 0` e a coluna não ser estruturalmente not-nullable.

    Args:
        coluna: coluna analisada a avaliar.
        metrica: MetricasBaseColuna da coluna, se já calculada.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        True se o teste soft de nulo deve ser sugerido.
    """
    if coluna.chave_primaria or coluna.nao_nulavel:
        return False
    if metrica is None or tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_SOFT:
        return False
    return 0 < metrica.percentual_nulo <= _LIMITE_NULO_SOFT


def _precisa_teste_soft_unico(
    coluna: ColunaAnalisada, metrica: MetricasBaseColuna | None, tamanho_amostra: int
) -> bool:
    """Decide se a coluna cai na faixa "quase única" (issue #90).

    Mutuamente exclusivo com o `unique` hard por construção: hard cobre
    `percentual_unico == 100.0` ou `coluna.unica`; aqui a faixa exige
    `percentual_unico < 100.0` e a coluna não ser estruturalmente única.

    Args:
        coluna: coluna analisada a avaliar.
        metrica: MetricasBaseColuna da coluna, se já calculada.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        True se o teste soft de unicidade deve ser sugerido.
    """
    if coluna.chave_primaria or coluna.unica:
        return False
    if metrica is None or tamanho_amostra < _TAMANHO_AMOSTRA_MINIMO_SOFT:
        return False
    return _LIMITE_UNICO_SOFT <= metrica.percentual_unico < 100.0


def _sugestoes_de_teste(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
    tamanho_amostra: int,
    colunas_em_fk_composta: set[str],
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis a uma coluna.

    `unique`/`not_null` combinam o fato estrutural do schema
    (`coluna.unica`/`coluna.nao_nulavel`) com a métrica amostral
    (`percentual_unico == 100.0`/`percentual_nulo == 0.0`) — mesmo padrão já
    usado no GeradorMarkdown (#44) de priorizar o fato do schema sobre a
    estimativa amostral. Ambos são suprimidos quando a coluna já é PK (PK
    implica os dois, sugerir seria redundante). A checagem amostral só
    entra em jogo com `tamanho_amostra > 0` — sem isso,
    `_metricas_vazias()` zera `percentual_nulo` pra amostra vazia, e o
    Gerador sugeriria `not_null`/`unique` sobre zero evidência real; o fato
    estrutural do schema continua valendo independente disso.

    `relationships` só é sugerido quando a tabela referenciada pela FK
    também está no lote analisado nesta execução — apontar `ref()` para um
    model que este Gerador não produziu quebraria `dbt run`. Quando a
    referência está fora do lote, emite `Aviso` e omite o teste.

    **FK composta (issue #95):** uma coluna que pertence a
    `colunas_em_fk_composta` nunca recebe o `relationships` per-coluna,
    mesmo tendo `chave_estrangeira=True`/`referencia` preenchida — o teste
    real pra ela é o model-level `composite_relationships` (ver
    `_testes_de_modelo`), que testa a combinação das colunas juntas, não
    cada uma isoladamente (limitação conhecida desde a #56, fechada aqui).

    `accepted_values` usa `severity: warn` e só é sugerido quando
    `_elegivel_para_enumeracao` aprova a coluna (issue #95): categoria de
    dado não monotônica/incompatível (`TIMESTAMP`/`DATE`/`TIME`/`UUID`/
    `JSON`/`ARRAY` excluídas), amostra acima do piso mínimo, contagem real
    de distintos abaixo do teto de cardinalidade, `percentual_unico < 10.0`
    e cobertura dos top-10 `valores_frequentes` sobre os não-nulos da
    amostra acima do mínimo exigido — é um teste de enumeração exaustiva
    calculado sobre uma amostra parcial, não a população completa, então um
    valor de cauda longa fora da amostra não deve quebrar CI silenciosamente,
    e os critérios adicionais evitam sugerir enumeração pra colunas que só
    pareciam categóricas por amostra pequena ou tipo incompatível (ver
    `_metricas.py` para a justificativa completa de cada critério).

    `matches_format` (issue #90) é sugerido quando `formato_detectado` está
    presente, com `severity: warn` (ver `docs/low_level_design.md` para a
    justificativa e o escopo de engines suportadas).

    Testes "soft" de nulo/unicidade (issue #90) cobrem a faixa intermediária
    entre "sem sinal" e o `not_null`/`unique` hard — ver
    `_precisa_teste_soft_nulo`/`_precisa_teste_soft_unico` para as condições
    exatas e `docs/low_level_design.md` para a justificativa dos thresholds.

    Args:
        coluna: coluna analisada a avaliar.
        presentes: pares (nome_escopo, nome_tabela) de todas as tabelas do
            lote analisado nesta execução.
        avisos: lista de avisos acumulada pelo Gerador, alimentada quando
            uma FK referencia tabela fora do lote.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        colunas_em_fk_composta: nomes de coluna desta tabela que pertencem
            a alguma `RestricaoDeFkComposta` — suprime `relationships`
            per-coluna pra elas (issue #95).

    Returns:
        Lista de testes no formato aceito por `schema.yml` (strings para
        testes sem argumento, dicts para `relationships`/`accepted_values`).
    """
    testes: list[Any] = []
    metrica = _metrica_de_coluna(coluna)

    unico = coluna.unica or (
        tamanho_amostra > 0
        and metrica is not None
        and metrica.percentual_unico == 100.0
    )
    nao_nulo = coluna.nao_nulavel or (
        tamanho_amostra > 0 and metrica is not None and metrica.percentual_nulo == 0.0
    )
    if unico and not coluna.chave_primaria:
        testes.append("unique")
    if nao_nulo and not coluna.chave_primaria:
        testes.append("not_null")

    if metrica is not None and metrica.formato_detectado is not None:
        testes.append(
            {
                "matches_format": {
                    "format": metrica.formato_detectado,
                    "config": {"severity": "warn"},
                }
            }
        )

    if _precisa_teste_soft_nulo(coluna, metrica, tamanho_amostra):
        testes.append(
            {
                "dbt_utils.not_null_proportion": {
                    "at_least": round(1 - _LIMITE_NULO_SOFT / 100, 4),
                    "config": {"severity": "warn"},
                }
            }
        )
    if _precisa_teste_soft_unico(coluna, metrica, tamanho_amostra):
        testes.append(
            {
                "unique_percentage_at_least": {
                    "at_least": round(_LIMITE_UNICO_SOFT / 100, 4),
                    "config": {"severity": "warn"},
                }
            }
        )

    if (
        coluna.chave_estrangeira
        and coluna.referencia is not None
        and coluna.nome not in colunas_em_fk_composta
    ):
        referencia = coluna.referencia
        if (referencia.nome_escopo, referencia.nome_tabela) in presentes:
            nome_model_referenciado = _nome_model(
                referencia.nome_escopo, referencia.nome_tabela
            )
            testes.append(
                {
                    "relationships": {
                        "to": f"ref('{nome_model_referenciado}')",
                        "field": referencia.nome_coluna,
                    }
                }
            )
        else:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"Coluna '{coluna.nome}' referencia "
                        f"'{referencia.nome_escopo}.{referencia.nome_tabela}', fora "
                        "do lote analisado nesta execução — teste relationships "
                        "omitido."
                    ),
                    origem=_ORIGEM,
                )
            )

    elegivel = _elegivel_para_enumeracao(coluna, metrica, tamanho_amostra)
    if elegivel and metrica is not None:
        testes.append(
            {
                "accepted_values": {
                    "values": [valor for valor, _ in metrica.valores_frequentes],
                    "config": {"severity": "warn"},
                }
            }
        )

    return testes


def _coluna_schema_yaml(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
    tamanho_amostra: int,
    colunas_em_fk_composta: set[str],
) -> dict[str, Any]:
    """Monta a entrada de uma coluna em `schema.yml`.

    Args:
        coluna: coluna analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        avisos: lista de avisos acumulada pelo Gerador.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.
        colunas_em_fk_composta: nomes de coluna desta tabela que pertencem
            a alguma `RestricaoDeFkComposta` (issue #95).

    Returns:
        Dict com `name`, `description` opcional (de `papel_de_negocio`) e
        `tests` opcional (omitido quando nenhuma regra se aplica).
    """
    entrada: dict[str, Any] = {"name": coluna.nome}
    if coluna.papel_de_negocio:
        entrada["description"] = coluna.papel_de_negocio
    testes = _sugestoes_de_teste(
        coluna, presentes, avisos, tamanho_amostra, colunas_em_fk_composta
    )
    if testes:
        entrada["tests"] = testes
    return entrada


def _testes_de_modelo(
    tabela: TabelaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis no nível do model (tabela).

    Diferente de `_sugestoes_de_teste` (nível coluna), dois testes vivem
    aqui — ambos fatos estruturais do catálogo, com severidade padrão
    (`error`), não `warn` como `accepted_values` (não há razão estatística
    pra suavizar um fato estrutural):

    - `dbt_utils.unique_combination_of_columns` — um por `RestricaoUnica`
      (UNIQUE composto real do schema, issue #89).
    - `composite_relationships` — um por `RestricaoDeFkComposta` (FK
      composta real do schema, issue #95), só quando a tabela referenciada
      está no lote (mesma regra do `relationships` single-column); senão,
      `Aviso` + omissão.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado —
            usado só pela checagem de `composite_relationships`.
        avisos: lista de avisos acumulada pelo Gerador, alimentada quando
            uma FK composta referencia tabela fora do lote.

    Returns:
        Lista de testes no formato aceito por `schema.yml` (dicts).
    """
    testes: list[Any] = [
        {
            "dbt_utils.unique_combination_of_columns": {
                "combination_of_columns": list(restricao.colunas),
            }
        }
        for restricao in tabela.restricoes_unicas
    ]
    for restricao_fk in tabela.restricoes_fk_compostas:
        chave_referenciada = (
            restricao_fk.nome_escopo_referenciado,
            restricao_fk.nome_tabela_referenciada,
        )
        if chave_referenciada not in presentes:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"FK composta de '{tabela.nome_escopo}.{tabela.nome_tabela}' "
                        f"({', '.join(restricao_fk.colunas_locais)}) referencia "
                        f"'{chave_referenciada[0]}.{chave_referenciada[1]}', fora do "
                        "lote analisado nesta execução — teste "
                        "composite_relationships omitido."
                    ),
                    origem=_ORIGEM,
                )
            )
            continue
        nome_model_referenciado = _nome_model(*chave_referenciada)
        testes.append(
            {
                "composite_relationships": {
                    "column_names": list(restricao_fk.colunas_locais),
                    "to": f"ref('{nome_model_referenciado}')",
                    "field_names": list(restricao_fk.colunas_referenciadas),
                }
            }
        )
    return testes


def _model_schema_yaml(
    tabela: TabelaAnalisada, presentes: set[tuple[str, str]], avisos: list[Aviso]
) -> dict[str, Any]:
    """Monta a entrada de um staging model em `schema.yml`.

    Args:
        tabela: tabela analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        avisos: lista de avisos acumulada pelo Gerador.

    Returns:
        Dict com `name`, `description` opcional, `tests` opcional
        (model-level, ver `_testes_de_modelo`) e a lista de `columns`.
    """
    nome_model = _nome_model(tabela.nome_escopo, tabela.nome_tabela)
    entrada: dict[str, Any] = {"name": nome_model}
    if tabela.papel_de_negocio:
        entrada["description"] = tabela.papel_de_negocio
    testes_de_modelo = _testes_de_modelo(tabela, presentes, avisos)
    if testes_de_modelo:
        entrada["tests"] = testes_de_modelo
    tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
    colunas_em_fk_composta: set[str] = set()
    for restricao in tabela.restricoes_fk_compostas:
        colunas_em_fk_composta.update(restricao.colunas_locais)
    entrada["columns"] = [
        _coluna_schema_yaml(
            coluna, presentes, avisos, tamanho_amostra, colunas_em_fk_composta
        )
        for coluna in tabela.colunas
    ]
    return entrada


def _agrupar_por_escopo(
    tabelas: list[TabelaAnalisada],
) -> dict[str, list[TabelaAnalisada]]:
    """Agrupa tabelas por escopo, preservando a ordem de primeira aparição.

    Única fonte de agrupamento por escopo do Gerador — `GeradorDbt.__call__`,
    `_montar_sources` e `_renderizar_readme` reaproveitam este resultado em
    vez de reagrupar cada um por conta própria.

    Args:
        tabelas: tabelas do lote analisado, já ordenadas por
            `(nome_escopo, nome_tabela)`.

    Returns:
        Dict `{escopo: [TabelaAnalisada, ...]}`.
    """
    tabelas_por_escopo: dict[str, list[TabelaAnalisada]] = {}
    for tabela in tabelas:
        tabelas_por_escopo.setdefault(tabela.nome_escopo, []).append(tabela)
    return tabelas_por_escopo


def _precisa_matches_format(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se algum consumidor real de `macros/matches_format/` existe no lote.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se pelo menos uma coluna tem `formato_detectado` calculado —
        escrever os macros sem isso seria decoração no artefato gerado.
    """
    for tabela in tabelas:
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if metrica is not None and metrica.formato_detectado is not None:
                return True
    return False


def _precisa_unique_percentage_at_least(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se algum consumidor de `unique_percentage_at_least.sql` existe no lote.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se pelo menos uma coluna cai na faixa "soft" de unicidade (ver
        `_precisa_teste_soft_unico`).
    """
    for tabela in tabelas:
        tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if _precisa_teste_soft_unico(coluna, metrica, tamanho_amostra):
                return True
    return False


def _precisa_dbt_utils(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se `packages.yml` (dependência `dbt_utils`) precisa ser escrito.

    Dois consumidores reais possíveis: `dbt_utils.unique_combination_of_columns`
    (UNIQUE composto, issue #89) e `dbt_utils.not_null_proportion` (teste soft
    de nulo, issue #90) — sem nenhum dos dois, declarar a dependência seria
    decoração no artefato gerado (mesmo critério já aplicado na #89).

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se houver ao menos um consumidor real de `dbt_utils` no lote.
    """
    if any(tabela.restricoes_unicas for tabela in tabelas):
        return True
    for tabela in tabelas:
        tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
        for coluna in tabela.colunas:
            metrica = _metrica_de_coluna(coluna)
            if _precisa_teste_soft_nulo(coluna, metrica, tamanho_amostra):
                return True
    return False


def _precisa_composite_relationships(
    tabelas: list[TabelaAnalisada], presentes: set[tuple[str, str]]
) -> bool:
    """Indica se algum consumidor real de `macros/composite_relationships.sql` existe.

    Args:
        tabelas: tabelas do lote analisado.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.

    Returns:
        True se pelo menos uma `RestricaoDeFkComposta` referencia uma
        tabela presente no lote — sem isso, `_testes_de_modelo` só emite
        `Aviso` (fora do lote) e nunca gera o teste, então escrever o macro
        seria decoração no artefato gerado.
    """
    for tabela in tabelas:
        for restricao in tabela.restricoes_fk_compostas:
            chave_referenciada = (
                restricao.nome_escopo_referenciado,
                restricao.nome_tabela_referenciada,
            )
            if chave_referenciada in presentes:
                return True
    return False


def _montar_sources(
    escopo: str, tabelas_do_escopo: list[TabelaAnalisada]
) -> dict[str, Any]:
    """Monta o `sources.yml` de um único escopo.

    Args:
        escopo: nome do escopo — todas as tabelas em `tabelas_do_escopo`
            pertencem a ele.
        tabelas_do_escopo: tabelas desse escopo.

    Returns:
        Dict `{"version": 2, "sources": [{"name": escopo, "tables": [...]}]}`.
    """
    return {
        "version": 2,
        "sources": [
            {
                "name": escopo,
                "tables": [
                    {"name": tabela.nome_tabela} for tabela in tabelas_do_escopo
                ],
            }
        ],
    }


def _renderizar_readme(
    tabelas_por_escopo: dict[str, list[TabelaAnalisada]],
    gerado_em: str,
    usa_dbt_utils: bool,
    usa_matches_format: bool,
) -> str:
    """Renderiza o README.md do projeto dbt gerado, na raiz do projeto.

    Args:
        tabelas_por_escopo: tabelas do lote, já agrupadas por escopo
            (`_agrupar_por_escopo`).
        gerado_em: timestamp ISO 8601 da execução, compartilhado com
            `dbt_project.yml`.
        usa_dbt_utils: se `packages.yml` foi gerado nesta execução — o bloco
            de comandos só menciona `dbt deps` quando há dependência real
            a instalar (issue #89).
        usa_matches_format: se `macros/matches_format/` foi gerado nesta
            execução — a nota sobre engines suportadas (Postgres/MariaDB
            nesta v1) só aparece quando há consumidor real (issue #90).

    Returns:
        Markdown listando os escopos e tabelas cobertos, com o caminho real
        de cada staging model — calculado via `_nome_model`, nunca
        remontado à parte no template, pra não divergir se a convenção de
        nome do model mudar.
    """
    escopos = [
        {
            "nome": escopo,
            "tabelas": [
                {
                    "nome": tabela.nome_tabela,
                    "caminho_sql": (
                        f"models/staging/{escopo}/"
                        f"{_nome_model(escopo, tabela.nome_tabela)}.sql"
                    ),
                }
                for tabela in tabelas
            ],
        }
        for escopo, tabelas in tabelas_por_escopo.items()
    ]
    return _TEMPLATE_README.render(
        escopos=escopos,
        gerado_em=gerado_em,
        usa_dbt_utils=usa_dbt_utils,
        usa_matches_format=usa_matches_format,
    )


def _dump_yaml(conteudo: dict[str, Any]) -> str:
    """Serializa um dict em YAML determinístico (ordem preservada, unicode)."""
    return yaml.safe_dump(conteudo, sort_keys=False, allow_unicode=True)


class GeradorDbt:
    """Gera um projeto dbt standalone (staging layer) a partir do BancoAnalisado."""

    requer: list[TipoDeMetrica] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Escreve dbt_project.yml, README.md e, por escopo, sources/models/schema.

        Cada escopo do lote vira uma subpasta autocontida em
        `models/staging/<escopo>/` (`sources.yml` + um `.sql` por tabela +
        `schema.yml`) — convenção real dbt-labs pra staging multi-source,
        consistente com `stg_<escopo>__<tabela>` já usado pra evitar colisão
        de nome de model entre escopos.

        Args:
            entrada: banco analisado cujas tabelas já devem ter
                MetricasBaseColuna calculada.
            destino: diretório raiz do projeto dbt gerado.

        Returns:
            Sucesso(None) com Aviso por FK que referencia tabela fora do
            lote analisado, ou Falha na primeira escrita em disco que
            falhar.
        """
        avisos: list[Aviso] = []
        tabelas = sorted(entrada.tabelas, key=lambda t: (t.nome_escopo, t.nome_tabela))
        presentes = {(tabela.nome_escopo, tabela.nome_tabela) for tabela in tabelas}
        tabelas_por_escopo = _agrupar_por_escopo(tabelas)
        usa_dbt_utils = _precisa_dbt_utils(tabelas)
        usa_matches_format = _precisa_matches_format(tabelas)
        usa_unique_percentage_at_least = _precisa_unique_percentage_at_least(tabelas)
        usa_composite_relationships = _precisa_composite_relationships(
            tabelas, presentes
        )

        gerado_em = datetime.now(UTC).isoformat()
        projeto = {**_DBT_PROJECT, "meta": {"generated_at": gerado_em}}
        resultado_projeto = escrever_arquivo(
            destino / "dbt_project.yml", _dump_yaml(projeto)
        )
        if isinstance(resultado_projeto, Falha):
            return resultado_projeto

        # packages.yml só existe quando há UNIQUE composto consumindo
        # dbt_utils de verdade nesta execução (issue #89) — declarar a
        # dependência sem consumidor seria decoração no artefato gerado.
        # Removido explicitamente quando não há mais consumidor, pra não
        # deixar um arquivo órfão de uma execução anterior (achado da
        # banca de revisão).
        caminho_packages = destino / "packages.yml"
        if usa_dbt_utils:
            resultado_packages = escrever_arquivo(
                caminho_packages, _dump_yaml(_PACKAGES_YML)
            )
            if isinstance(resultado_packages, Falha):
                return resultado_packages
        else:
            caminho_packages.unlink(missing_ok=True)

        # macros/matches_format/ e macros/unique_percentage_at_least.sql
        # (issue #90) seguem o mesmo princípio do packages.yml acima: só
        # existem com consumidor real no lote, removidos explicitamente
        # quando ficam órfãos numa execução nova.
        pasta_matches_format = destino / "macros" / "matches_format"
        if usa_matches_format:
            for nome_arquivo, conteudo in _CONTEUDO_MATCHES_FORMAT.items():
                resultado_macro = escrever_arquivo(
                    pasta_matches_format / nome_arquivo, conteudo
                )
                if isinstance(resultado_macro, Falha):
                    return resultado_macro
        elif pasta_matches_format.exists():
            shutil.rmtree(pasta_matches_format)

        caminho_unique_percentage = (
            destino / "macros" / "unique_percentage_at_least.sql"
        )
        if usa_unique_percentage_at_least:
            resultado_macro_unico = escrever_arquivo(
                caminho_unique_percentage, _CONTEUDO_UNIQUE_PERCENTAGE_AT_LEAST
            )
            if isinstance(resultado_macro_unico, Falha):
                return resultado_macro_unico
        else:
            caminho_unique_percentage.unlink(missing_ok=True)

        # macros/composite_relationships.sql (issue #95): mesmo princípio de
        # órfão condicional dos macros acima — só existe com consumidor
        # real (RestricaoDeFkComposta referenciando tabela presente no
        # lote), removido explicitamente quando fica órfão.
        caminho_composite_relationships = (
            destino / "macros" / "composite_relationships.sql"
        )
        if usa_composite_relationships:
            resultado_macro_composite = escrever_arquivo(
                caminho_composite_relationships, _CONTEUDO_COMPOSITE_RELATIONSHIPS
            )
            if isinstance(resultado_macro_composite, Falha):
                return resultado_macro_composite
        else:
            caminho_composite_relationships.unlink(missing_ok=True)

        resultado_readme = escrever_arquivo(
            destino / "README.md",
            _renderizar_readme(
                tabelas_por_escopo, gerado_em, usa_dbt_utils, usa_matches_format
            ),
        )
        if isinstance(resultado_readme, Falha):
            return resultado_readme

        for escopo, tabelas_do_escopo in tabelas_por_escopo.items():
            pasta_escopo = destino / "models" / "staging" / escopo

            resultado_sources = escrever_arquivo(
                pasta_escopo / "sources.yml",
                _dump_yaml(_montar_sources(escopo, tabelas_do_escopo)),
            )
            if isinstance(resultado_sources, Falha):
                return resultado_sources

            for tabela in tabelas_do_escopo:
                nome_model = _nome_model(tabela.nome_escopo, tabela.nome_tabela)
                caminho_sql = pasta_escopo / f"{nome_model}.sql"
                resultado_sql = escrever_arquivo(caminho_sql, _renderizar_sql(tabela))
                if isinstance(resultado_sql, Falha):
                    return resultado_sql

            schema: dict[str, Any] = {
                "version": 2,
                "models": [
                    _model_schema_yaml(tabela, presentes, avisos)
                    for tabela in tabelas_do_escopo
                ],
            }
            resultado_schema = escrever_arquivo(
                pasta_escopo / "schema.yml", _dump_yaml(schema)
            )
            if isinstance(resultado_schema, Falha):
                return resultado_schema

        return Sucesso(None, avisos=avisos)

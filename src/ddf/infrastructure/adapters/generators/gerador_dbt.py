"""GeradorDbt: projeto dbt standalone (staging layer) a partir do BancoAnalisado.

Única saída do sistema cujos identificadores no artefato (nomes de coluna/
tabela em `schema.yml`, `sources.yml` e no SQL, além do vocabulário de teste
`unique`/`not_null`/`relationships`/`accepted_values`) ficam em inglês — é o
contrato real consumido pelo dbt e pelo warehouse, não uma escolha de estilo
do código Python (ver `docs/engineer_guidelines.md`, "Nomenclatura: idioma
como contrato").
"""

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
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators._metricas import (
    _COBERTURA_MINIMA_ACCEPTED_VALUES,
    _cobertura_dos_valores_frequentes,
)

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

_ambiente = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 — saída é SQL/Markdown, não HTML
)
_TEMPLATE_SQL = _ambiente.get_template("stg_tabela.sql.jinja2")
_TEMPLATE_README = _ambiente.get_template("readme.md.jinja2")


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


def _sugestoes_de_teste(
    coluna: ColunaAnalisada,
    presentes: set[tuple[str, str]],
    avisos: list[Aviso],
    tamanho_amostra: int,
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

    **Limitação conhecida — FK composta:** o teste
    é gerado **por coluna**, uma `relationships` independente para cada
    coluna local apontando pro seu par referenciado. Isso testa que cada
    valor individual existe na coluna referenciada correspondente, **não**
    que a combinação das colunas juntas forma uma linha válida na tabela
    referenciada — a integridade referencial real de uma FK composta.
    `ColunaAnalisada.referencia` é modelado por coluna (`ReferenciaDeColuna`
    não agrupa colunas de uma mesma constraint), então este Gerador não tem
    como saber que duas colunas pertencem à mesma FK composta pra emitir um
    teste único sobre o par. Modelar isso exigiria agrupar colunas de uma
    mesma constraint composta já no Extraction Context — mudança de escopo
    maior, avaliada e adiada nesta issue.

    `accepted_values` usa `severity: warn` e só é sugerido quando os top-10
    `valores_frequentes` cobrem pelo menos `_COBERTURA_MINIMA_ACCEPTED_VALUES`
    dos valores **não-nulos** da amostra (ver
    `_cobertura_dos_valores_frequentes`): é um teste de enumeração exaustiva
    calculado sobre uma amostra parcial, não a população completa, então um
    valor de cauda longa fora da amostra não deve quebrar CI silenciosamente
    — e uma cobertura baixa é sinal de que a lista está longe de ser
    exaustiva mesmo dentro do próprio universo não-nulo amostrado.

    Args:
        coluna: coluna analisada a avaliar.
        presentes: pares (nome_escopo, nome_tabela) de todas as tabelas do
            lote analisado nesta execução.
        avisos: lista de avisos acumulada pelo Gerador, alimentada quando
            uma FK referencia tabela fora do lote.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

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

    if coluna.chave_estrangeira and coluna.referencia is not None:
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

    categorica = (
        metrica is not None
        and metrica.valores_frequentes
        and metrica.percentual_unico < 10.0
    )
    if categorica and metrica is not None:
        cobertura = _cobertura_dos_valores_frequentes(metrica, tamanho_amostra)
        if cobertura >= _COBERTURA_MINIMA_ACCEPTED_VALUES:
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
) -> dict[str, Any]:
    """Monta a entrada de uma coluna em `schema.yml`.

    Args:
        coluna: coluna analisada a documentar.
        presentes: pares (nome_escopo, nome_tabela) do lote analisado.
        avisos: lista de avisos acumulada pelo Gerador.
        tamanho_amostra: total de linhas amostradas da tabela desta coluna.

    Returns:
        Dict com `name`, `description` opcional (de `papel_de_negocio`) e
        `tests` opcional (omitido quando nenhuma regra se aplica).
    """
    entrada: dict[str, Any] = {"name": coluna.nome}
    if coluna.papel_de_negocio:
        entrada["description"] = coluna.papel_de_negocio
    testes = _sugestoes_de_teste(coluna, presentes, avisos, tamanho_amostra)
    if testes:
        entrada["tests"] = testes
    return entrada


def _testes_de_modelo(restricoes_unicas: list[RestricaoUnica]) -> list[Any]:
    """Sugere os testes dbt de qualidade aplicáveis no nível do model (tabela).

    Diferente de `_sugestoes_de_teste` (nível coluna), hoje o único teste
    model-level é `dbt_utils.unique_combination_of_columns` — um por
    `RestricaoUnica` (UNIQUE composto real do schema, issue #89). Usa
    severidade padrão (`error`), não `warn` como `accepted_values`: é fato
    estrutural do catálogo, não estimativa sobre amostra.

    Args:
        restricoes_unicas: UNIQUE compostos reais da tabela.

    Returns:
        Lista de testes no formato aceito por `schema.yml` (dicts), uma
        entrada `dbt_utils.unique_combination_of_columns` por restrição.
    """
    return [
        {
            "dbt_utils.unique_combination_of_columns": {
                "combination_of_columns": list(restricao.colunas),
            }
        }
        for restricao in restricoes_unicas
    ]


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
    testes_de_modelo = _testes_de_modelo(tabela.restricoes_unicas)
    if testes_de_modelo:
        entrada["tests"] = testes_de_modelo
    tamanho_amostra = tabela.metadados_amostra.tamanho_amostra
    entrada["columns"] = [
        _coluna_schema_yaml(coluna, presentes, avisos, tamanho_amostra)
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
        escopos=escopos, gerado_em=gerado_em, usa_dbt_utils=usa_dbt_utils
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
        usa_dbt_utils = any(tabela.restricoes_unicas for tabela in tabelas)

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

        resultado_readme = escrever_arquivo(
            destino / "README.md",
            _renderizar_readme(tabelas_por_escopo, gerado_em, usa_dbt_utils),
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

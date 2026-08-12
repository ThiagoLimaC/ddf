"""GeradorDbt: projeto dbt standalone (staging layer) a partir do BancoAnalisado.

Única saída do sistema cujos identificadores no artefato (nomes de coluna/
tabela em `schema.yml`, `sources.yml` e no SQL, além do vocabulário de teste
`unique`/`not_null`/`relationships`/`accepted_values`) ficam em inglês — é o
contrato real consumido pelo dbt e pelo warehouse, não uma escolha de estilo
do código Python (ver `docs/engineer_guidelines.md`, "Nomenclatura: idioma
como contrato").

Módulo reduzido a orquestração — cast/render SQL em `_sql.py`, heurística de
sugestão de teste em `_testes.py`, montagem de YAML/README em `_yaml.py`,
carregamento de templates/macros em `_templates.py`.
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ddf.domain.model.analysis import BancoAnalisado, MetricasBaseColuna, TipoDeMetrica
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.generators.comum._escrita import escrever_arquivo
from ddf.infrastructure.adapters.generators.dbt._sql import (
    _nome_model,
    _precisa_cast_type,
    _renderizar_sql,
    _tabela_com_nome_model_invalido,
    _tem_coluna_bigint,
)
from ddf.infrastructure.adapters.generators.dbt._templates import (
    _CONTEUDO_CAST_TYPE,
    _CONTEUDO_COMPOSITE_RELATIONSHIPS,
    _CONTEUDO_MATCHES_FORMAT,
    _CONTEUDO_UNIQUE_PERCENTAGE_AT_LEAST,
)
from ddf.infrastructure.adapters.generators.dbt._testes import (
    ContadoresDeAviso,
    _precisa_composite_relationships,
    _precisa_dbt_utils,
    _precisa_matches_format,
    _precisa_unique_percentage_at_least,
)
from ddf.infrastructure.adapters.generators.dbt._yaml import (
    _agrupar_por_escopo,
    _dump_yaml,
    _model_schema_yaml,
    _montar_sources,
    _renderizar_readme,
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
            Sucesso(None) com um Aviso agregado por categoria (FK composta,
            FK polimórfica, FK fora do lote) quando aplicável — não um
            Aviso por ocorrência, ver `ContadoresDeAviso` — ou Falha se
            algum nome de model gerado não for um identificador dbt válido
            (verificado antes de qualquer escrita, sem normalização
            silenciosa) ou na primeira escrita em disco que falhar.
        """
        contadores = ContadoresDeAviso()
        tabelas = sorted(entrada.tabelas, key=lambda t: (t.nome_escopo, t.nome_tabela))

        tabela_invalida = _tabela_com_nome_model_invalido(tabelas)
        if tabela_invalida is not None:
            nome_model = _nome_model(
                tabela_invalida.nome_escopo, tabela_invalida.nome_tabela
            )
            return Falha(
                f"Nome de model '{nome_model}' (escopo "
                f"'{tabela_invalida.nome_escopo}', tabela "
                f"'{tabela_invalida.nome_tabela}') não é um identificador dbt "
                "válido — só letras, dígitos e underscore, sem começar por "
                "dígito. Renomeie o escopo/tabela na fonte ou use um override "
                "antes de gerar o projeto dbt."
            )

        presentes = {(tabela.nome_escopo, tabela.nome_tabela) for tabela in tabelas}
        tabelas_por_escopo = _agrupar_por_escopo(tabelas)
        usa_dbt_utils = _precisa_dbt_utils(tabelas)
        usa_cast_type = _precisa_cast_type(tabelas)
        usa_bigint = _tem_coluna_bigint(tabelas)
        usa_matches_format = _precisa_matches_format(tabelas)
        usa_unique_percentage_at_least = _precisa_unique_percentage_at_least(tabelas)
        usa_composite_relationships = _precisa_composite_relationships(
            tabelas, presentes
        )

        gerado_em = datetime.now(UTC).isoformat()
        projeto = {
            **_DBT_PROJECT,
            "models": {
                "ddf_staging": {
                    **_DBT_PROJECT["models"]["ddf_staging"],
                    "+meta": {"generated_at": gerado_em},
                },
            },
        }
        resultado_projeto = escrever_arquivo(
            destino / "dbt_project.yml", _dump_yaml(projeto)
        )
        if isinstance(resultado_projeto, Falha):
            return resultado_projeto

        # packages.yml só existe quando há UNIQUE composto consumindo
        # dbt_utils de verdade nesta execução — declarar a dependência sem
        # consumidor seria decoração no artefato gerado. Removido
        # explicitamente quando não há mais consumidor, pra não deixar um
        # arquivo órfão de uma execução anterior.
        caminho_packages = destino / "packages.yml"
        if usa_dbt_utils:
            resultado_packages = escrever_arquivo(
                caminho_packages, _dump_yaml(_PACKAGES_YML)
            )
            if isinstance(resultado_packages, Falha):
                return resultado_packages
        else:
            caminho_packages.unlink(missing_ok=True)

        # macros/cast_type/: mesmo princípio de órfão condicional dos demais
        # macros — só existe com consumidor real (coluna cujo tipo canônico
        # exige tradução por adapter, ver _CATEGORIAS_DISPATCHADAS),
        # removido explicitamente quando fica órfão.
        pasta_cast_type = destino / "macros" / "cast_type"
        if usa_cast_type:
            for nome_arquivo, conteudo in _CONTEUDO_CAST_TYPE.items():
                resultado_macro_cast = escrever_arquivo(
                    pasta_cast_type / nome_arquivo, conteudo
                )
                if isinstance(resultado_macro_cast, Falha):
                    return resultado_macro_cast
        elif pasta_cast_type.exists():
            shutil.rmtree(pasta_cast_type)

        # macros/matches_format/ e macros/unique_percentage_at_least.sql
        # seguem o mesmo princípio do packages.yml acima: só existem com
        # consumidor real no lote, removidos explicitamente quando ficam
        # órfãos numa execução nova.
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

        # macros/composite_relationships.sql: mesmo princípio de órfão
        # condicional dos macros acima — só existe com consumidor real
        # (RestricaoDeFkComposta referenciando tabela presente no lote),
        # removido explicitamente quando fica órfão.
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
                tabelas_por_escopo,
                gerado_em,
                usa_dbt_utils,
                usa_matches_format,
                usa_bigint,
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
                    _model_schema_yaml(tabela, presentes, contadores)
                    for tabela in tabelas_do_escopo
                ],
            }
            resultado_schema = escrever_arquivo(
                pasta_escopo / "schema.yml", _dump_yaml(schema)
            )
            if isinstance(resultado_schema, Falha):
                return resultado_schema

        avisos: list[Aviso] = []
        if contadores.fk_composta_fora_do_lote:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"{contadores.fk_composta_fora_do_lote} FK(s) composta(s) "
                        "referenciam tabela fora do lote analisado — teste "
                        "composite_relationships omitido."
                    ),
                    origem=_ORIGEM,
                )
            )
        if contadores.fk_polimorfica:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"{contadores.fk_polimorfica} coluna(s) com FK polimórfica "
                        "(múltiplas referências sem discriminator) — teste "
                        "relationships automático omitido."
                    ),
                    origem=_ORIGEM,
                )
            )
        if contadores.fk_fora_do_lote:
            avisos.append(
                Aviso(
                    mensagem=(
                        f"{contadores.fk_fora_do_lote} coluna(s) referenciam tabela "
                        "fora do lote analisado — teste relationships omitido."
                    ),
                    origem=_ORIGEM,
                )
            )
        return Sucesso(None, avisos=avisos)

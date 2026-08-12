"""Testes de GeradorDbt: caminho feliz, erro de disco, bordas e determinismo."""

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import ddf.infrastructure.adapters.generators.dbt.gerador_dbt as gerador_dbt_modulo
from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    TabelaAnalisada,
)
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.analyzers.comum.detector_de_formato import _REGEXES
from ddf.infrastructure.adapters.generators.dbt.gerador_dbt import GeradorDbt

_CAMINHO_MACRO_MATCHES_FORMAT = (
    Path(gerador_dbt_modulo.__file__).parent
    / "templates"
    / "macros"
    / "matches_format"
    / "matches_format.sql"
)
_CAMINHO_MACRO_CAST_TYPE = (
    Path(gerador_dbt_modulo.__file__).parent
    / "templates"
    / "macros"
    / "cast_type"
    / "cast_type.sql"
)


def _schema_yml(destino: Path, escopo: str = "escopo") -> dict[str, Any]:
    conteudo = (destino / "models" / "staging" / escopo / "schema.yml").read_text()
    resultado: dict[str, Any] = yaml.safe_load(conteudo)
    return resultado


def _modelo(schema: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(m for m in schema["models"] if m["name"] == nome)


def _coluna(modelo: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(c for c in modelo["columns"] if c["name"] == nome)


def _accepted_values(coluna_yaml: dict[str, Any]) -> dict[str, Any] | None:
    testes = coluna_yaml.get("tests", [])
    dicts = [t for t in testes if isinstance(t, dict) and "accepted_values" in t]
    return dicts[0]["accepted_values"] if dicts else None


class TestFeliz:
    """Caminho feliz."""

    def test_caminho_feliz_gera_artefatos_por_escopo(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Duas tabelas em escopos diferentes geram subpastas autocontidas por escopo.

        `models/staging/vendas/` e `models/staging/rh/` cada um com seu próprio
        `sources.yml`/`.sql`/`schema.yml` — sem tabela de um escopo vazando pro
        `schema.yml` do outro (issue #77).
        """
        metrica_unica = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=100.0, valores_frequentes=[]
        )
        metrica_nao_nula = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=50.0, valores_frequentes=[]
        )
        metrica_categorica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=5.0,
            valores_frequentes=[("ativo", 90), ("inativo", 10)],
        )
        coluna_id = construir_coluna(
            nome="id",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
            chave_primaria=True,
            metricas=[metrica_unica],
        )
        coluna_email = construir_coluna(
            nome="email",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=255),
            metricas=[metrica_nao_nula],
        )
        coluna_status = construir_coluna(
            nome="status",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=10),
            metricas=[metrica_categorica],
        )
        coluna_perfil_id = construir_coluna(
            nome="perfil_id",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="rh", nome_tabela="perfis", nome_coluna="id"
                ),
            ],
            metricas=[metrica_nao_nula],
        )
        tabela_clientes = construir_tabela(
            colunas=[coluna_id, coluna_email, coluna_status, coluna_perfil_id],
            nome_tabela="clientes",
            nome_escopo="vendas",
        )
        coluna_perfil_id_pk = construir_coluna(
            nome="id",
            tipo_dado=TipoDeDado(
                categoria=CategoriaDeDado.NUMERIC, precisao=10, escala=2
            ),
            chave_primaria=True,
            metricas=[metrica_unica],
        )
        tabela_perfis = construir_tabela(
            colunas=[coluna_perfil_id_pk], nome_tabela="perfis", nome_escopo="rh"
        )
        banco = construir_banco([tabela_clientes, tabela_perfis])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert (tmp_path / "dbt_project.yml").exists()
        assert (tmp_path / "README.md").exists()
        assert (tmp_path / "models" / "staging" / "vendas" / "sources.yml").exists()
        assert (tmp_path / "models" / "staging" / "rh" / "sources.yml").exists()
        assert (
            tmp_path / "models" / "staging" / "vendas" / "stg_vendas__clientes.sql"
        ).exists()
        assert (tmp_path / "models" / "staging" / "rh" / "stg_rh__perfis.sql").exists()
        assert (tmp_path / "models" / "staging" / "vendas" / "schema.yml").exists()
        assert (tmp_path / "models" / "staging" / "rh" / "schema.yml").exists()

        sources_vendas = yaml.safe_load(
            (tmp_path / "models" / "staging" / "vendas" / "sources.yml").read_text()
        )
        assert [s["name"] for s in sources_vendas["sources"]] == ["vendas"]
        sources_rh = yaml.safe_load(
            (tmp_path / "models" / "staging" / "rh" / "sources.yml").read_text()
        )
        assert [s["name"] for s in sources_rh["sources"]] == ["rh"]

        sql_clientes = (
            tmp_path / "models" / "staging" / "vendas" / "stg_vendas__clientes.sql"
        ).read_text()
        linhas_sql = sql_clientes.splitlines()
        assert linhas_sql[0] == "select"
        assert linhas_sql[1] == (
            "    CAST({{ adapter.quote('id') }} AS INTEGER)"
            " as {{ adapter.quote('id') }},"
        )
        assert linhas_sql[2] == (
            "    CAST({{ adapter.quote('email') }} AS VARCHAR(255))"
            " as {{ adapter.quote('email') }},"
        )
        assert linhas_sql[3] == (
            "    CAST({{ adapter.quote('status') }} AS VARCHAR(10))"
            " as {{ adapter.quote('status') }},"
        )
        assert linhas_sql[4] == (
            "    CAST({{ adapter.quote('perfil_id') }} AS INTEGER)"
            " as {{ adapter.quote('perfil_id') }}"
        )  # sem vírgula
        assert linhas_sql[5] == "from {{ source('vendas', 'clientes') }}"

        sql_perfis = (
            tmp_path / "models" / "staging" / "rh" / "stg_rh__perfis.sql"
        ).read_text()
        assert (
            "CAST({{ adapter.quote('id') }} AS DECIMAL(10,2))"
            " as {{ adapter.quote('id') }}"
        ) in sql_perfis

        schema_vendas = _schema_yml(tmp_path, "vendas")
        nomes_models_vendas = [m["name"] for m in schema_vendas["models"]]
        assert nomes_models_vendas == ["stg_vendas__clientes"]  # não vaza rh

        schema_rh = _schema_yml(tmp_path, "rh")
        nomes_models_rh = [m["name"] for m in schema_rh["models"]]
        assert nomes_models_rh == ["stg_rh__perfis"]  # não vaza vendas

        modelo_clientes = _modelo(schema_vendas, "stg_vendas__clientes")

        coluna_id_yaml = _coluna(modelo_clientes, "id")
        assert "tests" not in coluna_id_yaml  # PK suprime unique/not_null redundante

        coluna_email_yaml = _coluna(modelo_clientes, "email")
        testes_email = coluna_email_yaml["tests"]
        assert {"not_null": {"config": {"severity": "warn"}}} in testes_email

        coluna_status_yaml = _coluna(modelo_clientes, "status")
        testes_status = coluna_status_yaml["tests"]
        accepted = next(
            t for t in testes_status if isinstance(t, dict) and "accepted_values" in t
        )
        assert accepted["accepted_values"]["values"] == ["ativo", "inativo"]
        assert accepted["accepted_values"]["config"]["severity"] == "warn"

        coluna_perfil_yaml = _coluna(modelo_clientes, "perfil_id")
        testes_perfil = coluna_perfil_yaml["tests"]
        relacionamento = next(
            t for t in testes_perfil if isinstance(t, dict) and "relationships" in t
        )
        assert relacionamento["relationships"]["to"] == "ref('stg_rh__perfis')"
        assert relacionamento["relationships"]["field"] == "id"

    def test_dbt_project_registra_generated_at(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """dbt_project.yml registra meta.generated_at (issue #56)."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        projeto = yaml.safe_load((tmp_path / "dbt_project.yml").read_text())
        datetime.fromisoformat(
            projeto["meta"]["generated_at"]
        )  # ValueError se malformado

    def test_readme_lista_escopos_e_tabelas_do_lote(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """README.md na raiz lista os escopos/tabelas do lote gerado (issue #77).

        Verifica a linha completa com o caminho do `.sql`, não só substrings
        soltas — pega divergência entre o README e `_nome_model` (única fonte
        real da convenção de nome do staging model), que um `in readme` solto
        não pegaria se o template reconstruísse o nome por conta própria.
        """
        tabela_clientes = construir_tabela(
            colunas=[construir_coluna()], nome_tabela="clientes", nome_escopo="vendas"
        )
        tabela_perfis = construir_tabela(
            colunas=[construir_coluna()], nome_tabela="perfis", nome_escopo="rh"
        )
        banco = construir_banco([tabela_clientes, tabela_perfis])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        readme = (tmp_path / "README.md").read_text()
        assert "Gerado em:" in readme
        assert (
            "- `clientes` → `models/staging/vendas/stg_vendas__clientes.sql`" in readme
        )
        assert "- `perfis` → `models/staging/rh/stg_rh__perfis.sql`" in readme

    def test_packages_yml_nao_e_gerado_sem_unique_composto(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem UNIQUE composto no lote, packages.yml não é gerado (issue #89).

        Declarar dbt_utils como dependência sem consumidor real seria decoração
        no artefato gerado — mesmo argumento já usado na issue original.
        """
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "packages.yml").exists()
        readme = (tmp_path / "README.md").read_text()
        assert "dbt deps" not in readme

    def test_packages_yml_e_teste_model_level_com_unique_composto(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """UNIQUE composto gera packages.yml + teste model-level (issue #89).

        Severidade padrão (sem `config: severity`), diferente de
        `accepted_values` — é fato estrutural do schema, não amostral.
        """
        coluna_a = construir_coluna(nome="codigo_pais")
        coluna_b = construir_coluna(nome="codigo_local")
        tabela = construir_tabela(
            colunas=[coluna_a, coluna_b],
            restricoes_unicas=[RestricaoUnica(colunas=("codigo_pais", "codigo_local"))],
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        packages = yaml.safe_load((tmp_path / "packages.yml").read_text())
        assert packages == {
            "packages": [
                {"package": "dbt-labs/dbt_utils", "version": [">=1.0.0", "<2.0.0"]}
            ]
        }
        readme = (tmp_path / "README.md").read_text()
        assert "dbt deps" in readme

        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        assert modelo["tests"] == [
            {
                "dbt_utils.unique_combination_of_columns": {
                    "combination_of_columns": ["codigo_pais", "codigo_local"],
                }
            }
        ]

    def test_falha_ao_nao_conseguir_escrever_em_disco(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Destino sem permissão de criar o dbt_project.yml retorna Falha com o path."""
        obstaculo = tmp_path / "dbt_project.yml"
        obstaculo.mkdir()
        (obstaculo / "arquivo_dentro_do_diretorio").write_text("bloqueia o write_text")

        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Falha)
        assert str(obstaculo) in resultado.erro

    def test_coluna_sem_metrica_e_sem_fato_estrutural_nao_sugere_teste(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna sem MetricasBaseColuna e sem unica/nao_nulavel não recebe testes."""
        coluna = construir_coluna(nome="observacao", metricas=[])
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "observacao")
        assert "tests" not in coluna_yaml

    def test_fk_fora_do_lote_emite_aviso_e_omite_relationships(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """FK para tabela fora do BancoAnalisado gera Aviso, sem relationships."""
        coluna_fk = construir_coluna(
            nome="funcionario_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="rh", nome_tabela="funcionarios", nome_coluna="id"
                ),
            ],
            metricas=[],
        )
        tabela = construir_tabela(
            colunas=[coluna_fk], nome_tabela="pedidos", nome_escopo="vendas"
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert "1 coluna(s)" in resultado.avisos[0].mensagem
        assert "fora do lote" in resultado.avisos[0].mensagem

        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__pedidos")
        coluna_yaml = _coluna(modelo, "funcionario_id")
        assert "tests" not in coluna_yaml

    def test_varias_colunas_com_fk_fora_do_lote_colapsam_em_um_aviso(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Várias colunas com FK fora do lote geram um único Aviso, não por coluna."""
        coluna_funcionario = construir_coluna(
            nome="funcionario_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="rh", nome_tabela="funcionarios", nome_coluna="id"
                ),
            ],
            metricas=[],
        )
        coluna_filial = construir_coluna(
            nome="filial_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="rh", nome_tabela="filiais", nome_coluna="id"
                ),
            ],
            metricas=[],
        )
        tabela = construir_tabela(
            colunas=[coluna_funcionario, coluna_filial],
            nome_tabela="pedidos",
            nome_escopo="vendas",
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert "2 coluna(s)" in resultado.avisos[0].mensagem

    def test_fk_polimorfica_com_2_mais_referencias_suprime_relationships_e_avisa(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna com 2+ FKs distintas (issue #105) não recebe relationships.

        Testar "toda linha satisfaz a relação A" seria falso positivo
        garantido quando a linha na verdade satisfaz a relação B — em vez
        de escolher uma referência arbitrária pra testar, o Gerador não
        emite teste automático nenhum e explica a ambiguidade via Aviso.
        """
        coluna_fk = construir_coluna(
            nome="entidade_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
                ),
            ],
            metricas=[],
        )
        tabela = construir_tabela(
            colunas=[coluna_fk], nome_tabela="movimentos", nome_escopo="vendas"
        )
        clientes = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="clientes",
            nome_escopo="vendas",
        )
        fornecedores = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="fornecedores",
            nome_escopo="vendas",
        )
        banco = construir_banco([tabela, clientes, fornecedores])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert "1 coluna(s)" in resultado.avisos[0].mensagem
        assert "FK polimórfica" in resultado.avisos[0].mensagem

        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__movimentos")
        coluna_yaml = _coluna(modelo, "entidade_id")
        assert "tests" not in coluna_yaml

    def test_fk_polimorfica_com_3_referencias_tambem_suprime_relationships(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Borda: 3+ referências (não só 2) continuam suprimindo o teste.

        Prova que `len(referencias) > 1` generaliza de verdade, não só
        para o caso de 2 referências.
        """
        coluna_fk = construir_coluna(
            nome="entidade_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="parceiros", nome_coluna="id"
                ),
            ],
            metricas=[],
        )
        tabela = construir_tabela(
            colunas=[coluna_fk], nome_tabela="movimentos", nome_escopo="vendas"
        )
        clientes = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="clientes",
            nome_escopo="vendas",
        )
        fornecedores = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="fornecedores",
            nome_escopo="vendas",
        )
        parceiros = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="parceiros",
            nome_escopo="vendas",
        )
        banco = construir_banco([tabela, clientes, fornecedores, parceiros])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert "1 coluna(s)" in resultado.avisos[0].mensagem
        assert "FK polimórfica" in resultado.avisos[0].mensagem

        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__movimentos")
        coluna_yaml = _coluna(modelo, "entidade_id")
        assert "tests" not in coluna_yaml

    def test_fk_composta_suprime_relationships_por_coluna_e_gera_teste_de_model(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """FK composta suprime relationships per-coluna e gera composite_relationships.

        Issue #95.

        Severidade padrão (sem `config: severity`) — mesma decisão de
        `dbt_utils.unique_combination_of_columns`, fato estrutural do schema.
        """
        coluna_pais = construir_coluna(
            nome="pais_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="geografia",
                    nome_tabela="estados",
                    nome_coluna="pais_id",
                ),
            ],
        )
        coluna_estado = construir_coluna(
            nome="estado_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="geografia", nome_tabela="estados", nome_coluna="id"
                ),
            ],
        )
        tabela = construir_tabela(
            colunas=[coluna_pais, coluna_estado],
            nome_tabela="pedidos",
            nome_escopo="vendas",
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="geografia",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        tabela_estados = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="estados",
            nome_escopo="geografia",
        )
        banco = construir_banco([tabela, tabela_estados])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__pedidos")

        coluna_pais_yaml = _coluna(modelo, "pais_id")
        assert "tests" not in coluna_pais_yaml
        coluna_estado_yaml = _coluna(modelo, "estado_id")
        assert "tests" not in coluna_estado_yaml

        assert modelo["tests"] == [
            {
                "composite_relationships": {
                    "column_names": ["pais_id", "estado_id"],
                    "to": "ref('stg_geografia__estados')",
                    "field_names": ["pais_id", "id"],
                }
            }
        ]

    def test_fk_composta_fora_do_lote_emite_aviso_e_omite_teste_de_model(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """FK composta fora do lote gera Aviso, sem o teste de model."""
        coluna_pais = construir_coluna(nome="pais_id")
        coluna_estado = construir_coluna(nome="estado_id")
        tabela = construir_tabela(
            colunas=[coluna_pais, coluna_estado],
            nome_tabela="pedidos",
            nome_escopo="vendas",
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="geografia",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert "1 FK(s) composta(s)" in resultado.avisos[0].mensagem

        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__pedidos")
        assert "tests" not in modelo

    def test_coluna_em_fk_composta_mantem_relationships_de_fk_propria(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna com FK composta + FK single-column própria mantém relationships.

        Achado 4 da issue #140: `tenant_id` participa de uma FK composta
        `(tenant_id, user_id) → users(tenant_id, id)` **e** tem uma FK
        single-column legítima e independente pra `tenants.id`.
        `ColunaAnalisada.referencias` acumula as duas — a supressão de
        `relationships` deve descartar só a entrada que corresponde à FK
        composta, não a coluna inteira.
        """
        coluna_tenant = construir_coluna(
            nome="tenant_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="tenants", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="users", nome_coluna="tenant_id"
                ),
            ],
        )
        coluna_user = construir_coluna(
            nome="user_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="users", nome_coluna="id"
                ),
            ],
        )
        tabela = construir_tabela(
            colunas=[coluna_tenant, coluna_user],
            nome_tabela="orders",
            nome_escopo="vendas",
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("tenant_id", "user_id"),
                    nome_escopo_referenciado="vendas",
                    nome_tabela_referenciada="users",
                    colunas_referenciadas=("tenant_id", "id"),
                )
            ],
        )
        tabela_tenants = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="tenants",
            nome_escopo="vendas",
        )
        tabela_users = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="users",
            nome_escopo="vendas",
        )
        banco = construir_banco([tabela, tabela_tenants, tabela_users])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []  # nada suprimido de fato, sem Aviso

        schema = _schema_yml(tmp_path, "vendas")
        modelo = _modelo(schema, "stg_vendas__orders")

        coluna_tenant_yaml = _coluna(modelo, "tenant_id")
        assert coluna_tenant_yaml["tests"] == [
            {"relationships": {"to": "ref('stg_vendas__tenants')", "field": "id"}}
        ]
        coluna_user_yaml = _coluna(modelo, "user_id")
        assert "tests" not in coluna_user_yaml  # só referência composta, suprimida

    def test_accepted_values_omitido_quando_top10_cobre_pouco_da_amostra(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Top-10 cobrindo pouco da amostra não sugere accepted_values.

        percentual_unico < 10.0 sozinho não basta: se os 10 valores mais
        frequentes somam só uma fração pequena da amostra (aqui, 8 de 100
        linhas), a lista está longe de ser exaustiva mesmo dentro da própria
        amostra — sugerir o teste seria enumerar um universo que não foi visto.

        `percentual_nulo=20.0` (fora da faixa hard `== 0.0` e da faixa soft
        `0 < x <= 10.0`, issue #90) para isolar essa asserção do teste soft de
        nulo, que dispararia à parte e tornaria o `"tests" not in coluna_yaml`
        abaixo falso por um motivo alheio ao que este teste verifica.
        """
        metrica_baixa_cobertura = MetricasBaseColuna(
            percentual_nulo=20.0,
            percentual_unico=5.0,
            valores_frequentes=[("a", 5), ("b", 3)],
        )
        coluna = construir_coluna(nome="categoria", metricas=[metrica_baixa_cobertura])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "categoria")
        assert "tests" not in coluna_yaml

    def test_accepted_values_considera_apenas_nao_nulos_no_denominador(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna com muitos nulos, mas exaustiva sobre os não-nulos, ainda sugere.

        `valores_frequentes` é calculado só sobre valores não-nulos
        (AnalisadorDeMetricasDeColuna usa `drop_nulls()`). Dividir a cobertura
        pelo tamanho total da amostra (em vez do total de não-nulos)
        penalizaria injustamente colunas categóricas com muitos nulos: aqui,
        60% da amostra é nula, mas os 40 valores não-nulos são cobertos 100%
        pelo top-10 — a enumeração é exaustiva sobre o que de fato existe.
        """
        metrica_com_muitos_nulos = MetricasBaseColuna(
            percentual_nulo=60.0,
            percentual_unico=2.0,
            valores_frequentes=[("ativo", 30), ("inativo", 10)],
        )
        coluna = construir_coluna(nome="status", metricas=[metrica_com_muitos_nulos])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "status")
        testes = coluna_yaml["tests"]
        accepted = next(t for t in testes if isinstance(t, dict))
        assert accepted["accepted_values"]["values"] == ["ativo", "inativo"]

    def test_timestamp_nunca_sugere_accepted_values_mesmo_com_cobertura_total(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """TIMESTAMP nunca sugere accepted_values, mesmo com cobertura/cardinalidade ok.

        Issue #95.

        Achado real: `criado_em` travado em 2 valores literais de data/hora
        numa amostra pequena passava nos critérios antigos (percentual_unico<10
        + cobertura>=0.9), mas datas são monotônicas por natureza — nenhuma
        amostra torna um "criado em" um universo fechado.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=2.0,
            valores_frequentes=[
                ("2024-01-01T00:00:00", 60),
                ("2024-01-02T00:00:00", 40),
            ],
        )
        coluna = construir_coluna(
            nome="criado_em",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP),
            metricas=[metrica],
        )
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "criado_em")
        assert _accepted_values(coluna_yaml) is None

    def test_amostra_abaixo_do_piso_nao_sugere_accepted_values(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Amostra abaixo do piso não sugere accepted_values, mesmo com cobertura total.

        Issue #95.

        Antes desta issue, o `GeradorDbt` não tinha piso de amostra — só
        `GeradorContextoDeIA` tinha (`_TAMANHO_AMOSTRA_MINIMO_ENUM`), e os dois
        divergiam por isso.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=5.0,
            valores_frequentes=[("a", 10), ("b", 10)],
        )
        coluna = construir_coluna(nome="flag", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=20)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "flag")
        assert _accepted_values(coluna_yaml) is None

    def test_exatamente_dez_distintos_reconstruidos_nao_sugere_accepted_values(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Teto de cardinalidade pega o que `percentual_unico<10` sozinho não pega.

        200 linhas, `percentual_unico=5.0` (passaria no critério antigo), mas a
        contagem de distintos reconstruída (`200 * 0.05 = 10`) bate o teto —
        `valores_frequentes` truncado em 10 não distingue "tem exatamente 10
        distintos" de "tem 200 e só vemos os 10 mais frequentes".
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=5.0,
            valores_frequentes=[(str(v), 20) for v in range(10)],
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=200)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "codigo")
        assert _accepted_values(coluna_yaml) is None

    def test_nove_distintos_com_amostra_e_cobertura_ok_sugere_accepted_values(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Abaixo do teto de cardinalidade, amostra e cobertura ok, ainda sugere (#95).

        200 linhas, `percentual_unico=4.5` reconstrói pra 9 distintos — abaixo
        do teto de 10 — e os 9 valores cobrem 190/200 (95%) da amostra.
        """
        valores_frequentes = [(str(v), 21) for v in range(8)] + [("8", 22)]
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=4.5,
            valores_frequentes=valores_frequentes,
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=200)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "codigo")
        testes = coluna_yaml["tests"]
        accepted = next(
            t for t in testes if isinstance(t, dict) and "accepted_values" in t
        )
        assert accepted["accepted_values"]["values"] == [str(v) for v in range(9)]

    def test_alta_cardinalidade_real_mascarada_por_nulos_nao_sugere_accepted_values(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Regressão: nulos não podem mascarar cardinalidade real alta (#95).

        1000 linhas, 90% nulas (100 não-nulas), `percentual_unico=6.0` — a
        contagem real de distintos é `1000 * 0.06 = 60`, bem acima do teto de
        10. A fórmula antiga de `_contagem_de_distintos` multiplicava de novo
        pelo não-nulo (`100 * 0.06 = 6`), passando incorretamente no teto de
        cardinalidade só porque a coluna tem muitos nulos — reintroduzindo o
        falso positivo que esta issue existe para eliminar.
        """
        valores_frequentes = [(str(v), 9) for v in range(9)] + [("9", 14)]
        metrica = MetricasBaseColuna(
            percentual_nulo=90.0,
            percentual_unico=6.0,
            valores_frequentes=valores_frequentes,
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=1000)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "codigo")
        assert _accepted_values(coluna_yaml) is None

    def test_coluna_unknown_nao_recebe_cast(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna de categoria UNKNOWN é projetada raw, sem CAST inseguro."""
        coluna = construir_coluna(
            nome="spatiallocation",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.UNKNOWN),
            metricas=[],
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path / "models" / "staging" / "escopo" / "stg_escopo__tabela.sql"
        ).read_text()
        assert (
            "{{ adapter.quote('spatiallocation') }}"
            " as {{ adapter.quote('spatiallocation') }}"
        ) in sql
        assert "CAST" not in sql

    def test_array_com_elemento_reconhecido_recebe_cast_de_array(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """ARRAY com elemento reconhecido vira CAST(col AS <TIPO>[])."""
        coluna = construir_coluna(
            nome="tags",
            tipo_dado=TipoDeDado(
                categoria=CategoriaDeDado.ARRAY, elemento=CategoriaDeDado.INTEGER
            ),
            metricas=[],
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path / "models" / "staging" / "escopo" / "stg_escopo__tabela.sql"
        ).read_text()
        assert "CAST({{ adapter.quote('tags') }} AS INTEGER[])" in sql

    def test_coluna_com_nome_reservado_e_quotada_no_sql(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna com nome de palavra reservada (`order`) sai sempre quotada.

        `adapter.quote()` resolve o delimitador certo por motor em tempo de
        compile (aspas duplas no Postgres, crase no MariaDB) — aspas duplas
        fixas não funcionam no MariaDB sem `ANSI_QUOTES`.
        """
        coluna = construir_coluna(nome="order")
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path / "models" / "staging" / "escopo" / "stg_escopo__tabela.sql"
        ).read_text()
        assert "CAST({{ adapter.quote('order') }} AS INTEGER)" in sql
        assert "as {{ adapter.quote('order') }}" in sql

    def test_geracao_e_deterministica(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """A mesma entrada produz exatamente os mesmos artefatos em duas execuções.

        `dbt_project.yml` é comparado à parte, excluindo `meta.generated_at` —
        esse campo captura o momento da geração de propósito (issue #56), então
        difere entre as duas execuções mesmo com entrada idêntica; o resto do
        arquivo continua determinístico.
        """
        coluna = construir_coluna(nome="id", metricas=[metrica_coluna_completa])
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])
        destino_a = tmp_path / "a"
        destino_b = tmp_path / "b"

        resultado_a = GeradorDbt()(banco, destino_a)
        resultado_b = GeradorDbt()(banco, destino_b)

        assert isinstance(resultado_a, Sucesso)
        assert isinstance(resultado_b, Sucesso)
        for relativo in (
            "models/staging/escopo/sources.yml",
            "models/staging/escopo/schema.yml",
            "models/staging/escopo/stg_escopo__tabela.sql",
        ):
            assert (destino_a / relativo).read_text() == (
                destino_b / relativo
            ).read_text()

        projeto_a = yaml.safe_load((destino_a / "dbt_project.yml").read_text())
        projeto_b = yaml.safe_load((destino_b / "dbt_project.yml").read_text())
        assert "generated_at" in projeto_a["meta"]
        del projeto_a["meta"]["generated_at"]
        del projeto_b["meta"]["generated_at"]
        assert projeto_a == projeto_b

    def test_macro_matches_format_cobre_todos_os_formatos_do_detector(
        self,
    ) -> None:
        """Contrato: os formatos embutidos no macro SQL casam com _REGEXES.

        detector_de_formato.py e matches_format.sql são duas fontes de verdade
        mantidas manualmente em paralelo (Python vs. SQL estático) — sem este
        teste, um formato novo adicionado a _REGEXES sem replicar no macro só
        quebraria em `dbt compile`/`dbt test` do usuário final, nunca no pytest
        do próprio ddf.
        """
        conteudo = _CAMINHO_MACRO_MATCHES_FORMAT.read_text()
        bloco_patterns = conteudo.split("{% set patterns = {")[1].split("} %}")[0]
        formatos_no_macro = set(re.findall(r"'(\w+)':", bloco_patterns))

        assert formatos_no_macro == set(_REGEXES.keys())

    def test_matches_format_sugerido_quando_formato_detectado(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna com formato_detectado sugere matches_format com severity warn."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0,
            percentual_unico=50.0,
            valores_frequentes=[],
            formato_detectado="email",
        )
        coluna = construir_coluna(nome="email", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "email")
        matches = next(
            t
            for t in coluna_yaml["tests"]
            if isinstance(t, dict) and "matches_format" in t
        )
        assert matches["matches_format"] == {
            "format": "email",
            "config": {"severity": "warn"},
        }

    def test_teste_soft_nulo_sugerido_entre_zero_e_limite(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual_nulo dentro de (0, 10] sugere dbt_utils.not_null_proportion."""
        metrica = MetricasBaseColuna(
            percentual_nulo=5.0, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "telefone")
        soft = next(
            t
            for t in coluna_yaml["tests"]
            if isinstance(t, dict) and "dbt_utils.not_null_proportion" in t
        )
        assert soft["dbt_utils.not_null_proportion"] == {
            "at_least": 0.9,
            "config": {"severity": "warn"},
        }

    def test_teste_soft_nulo_nao_duplica_quando_coluna_estruturalmente_not_nullable(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Estrutural: nao_nulavel=True recebe só not_null hard, sem soft duplicado."""
        metrica = MetricasBaseColuna(
            percentual_nulo=5.0, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", nao_nulavel=True, metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "telefone")
        assert coluna_yaml["tests"] == ["not_null"]

    def test_teste_soft_nulo_omitido_para_chave_primaria(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Estrutural: PK não recebe o teste soft de nulo mesmo dentro da faixa."""
        metrica = MetricasBaseColuna(
            percentual_nulo=5.0, percentual_unico=100.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="id", chave_primaria=True, metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "id")
        assert "tests" not in coluna_yaml

    def test_unique_not_null_amostral_com_amostra_no_piso_vira_warn(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem fato estrutural, amostra exatamente no piso já sugere unique/not_null.

        Cenário do achado 3 da issue #140: 100% único/0% nulo só na amostra
        (`coluna.unica`/`nao_nulavel` ambos False) não deve virar
        `severity: error` — o piso não elimina o risco de falso-positivo
        para um teste de valor extremo (diferente dos testes de faixa
        10%/95%), só o `severity: warn` protege o build.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=100.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="email", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        testes = _coluna(modelo, "email")["tests"]
        assert {"unique": {"config": {"severity": "warn"}}} in testes
        assert {"not_null": {"config": {"severity": "warn"}}} in testes

    def test_unique_not_null_amostral_abaixo_do_piso_nao_e_sugerido(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Amostra abaixo do piso (99) não sugere unique/not_null amostral."""
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=100.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="email", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=99)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "email")
        assert "tests" not in coluna_yaml

    def test_unique_not_null_estrutural_prevalece_sobre_amostral(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Fato estrutural do schema sempre gera severity: error, não warn."""
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=100.0, valores_frequentes=[]
        )
        coluna = construir_coluna(
            nome="email", unica=True, nao_nulavel=True, metricas=[metrica]
        )
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        testes = _coluna(modelo, "email")["tests"]
        assert "unique" in testes
        assert "not_null" in testes

    def test_teste_soft_unico_sugerido_entre_limite_e_cem(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual_unico dentro de [95, 100) sugere unique_percentage_at_least."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0, percentual_unico=97.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="cpf", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "cpf")
        soft = next(
            t
            for t in coluna_yaml["tests"]
            if isinstance(t, dict) and "unique_percentage_at_least" in t
        )
        assert soft["unique_percentage_at_least"] == {
            "at_least": 0.95,
            "config": {"severity": "warn"},
        }

    def test_teste_soft_unico_nao_duplica_quando_coluna_estruturalmente_unica(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Estrutural: coluna unica=True recebe só unique hard, sem soft duplicado."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0, percentual_unico=97.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="cpf", unica=True, metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "cpf")
        assert coluna_yaml["tests"] == ["unique"]

    def test_macros_matches_format_nao_gerados_sem_formato_detectado(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem formato_detectado no lote, macros/matches_format/ não é gerado."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "macros" / "matches_format").exists()

    def test_macros_matches_format_gerados_com_formato_detectado(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Com formato_detectado no lote, os 3 arquivos de matches_format/ existem."""
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=50.0,
            valores_frequentes=[],
            formato_detectado="email",
        )
        coluna = construir_coluna(nome="email", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        pasta = tmp_path / "macros" / "matches_format"
        assert (pasta / "matches_format.sql").read_text() == (
            _CAMINHO_MACRO_MATCHES_FORMAT.read_text()
        )
        assert (pasta / "postgres__validate_format.sql").exists()
        assert (pasta / "mariadb__validate_format.sql").exists()

    def test_macros_cast_type_nao_gerados_sem_categoria_dispatchada(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Só com categorias já portáveis (INTEGER), macros/cast_type/ não sai."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "macros" / "cast_type").exists()

    def test_macros_cast_type_gerados_com_categoria_dispatchada(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Com coluna BIGINT no lote, os 3 arquivos de cast_type/ existem."""
        coluna = construir_coluna(
            nome="id_externo", tipo_dado=TipoDeDado(categoria=CategoriaDeDado.BIGINT)
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        pasta = tmp_path / "macros" / "cast_type"
        assert (pasta / "cast_type.sql").read_text() == (
            _CAMINHO_MACRO_CAST_TYPE.read_text()
        )
        assert (pasta / "postgres__cast_type.sql").exists()
        assert (pasta / "mariadb__cast_type.sql").exists()

    def test_sql_de_coluna_bigint_chama_macro_cast_type(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna BIGINT vira `{{ cast_type(...) }}` no SQL, não CAST literal."""
        coluna = construir_coluna(
            nome="id_externo", tipo_dado=TipoDeDado(categoria=CategoriaDeDado.BIGINT)
        )
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", nome_escopo="vendas"
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path
            / "models"
            / "staging"
            / "vendas"
            / "stg_vendas__pedidos.sql"
        ).read_text()
        assert (
            "{{ cast_type(adapter.quote('id_externo'), 'BIGINT') }}" in sql
        )
        assert "CAST(id_externo AS BIGINT)" not in sql

    def test_sql_de_coluna_timestamp_com_precisao_passa_precisao_ao_macro(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """precisao_fracionaria vira 3º argumento posicional do macro."""
        coluna = construir_coluna(
            nome="criado_em",
            tipo_dado=TipoDeDado(
                categoria=CategoriaDeDado.TIMESTAMP,
                com_timezone=True,
                precisao_fracionaria=3,
            ),
        )
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", nome_escopo="vendas"
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path
            / "models"
            / "staging"
            / "vendas"
            / "stg_vendas__pedidos.sql"
        ).read_text()
        assert (
            "{{ cast_type(adapter.quote('criado_em'), "
            "'TIMESTAMP WITH TIME ZONE', 3) }}" in sql
        )

    def test_macro_unique_percentage_nao_gerado_sem_consumidor(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem coluna na faixa soft de unicidade, unique_percentage_at_least não sai."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "macros" / "unique_percentage_at_least.sql").exists()

    def test_macro_unique_percentage_gerado_com_consumidor(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Com coluna na faixa soft de unicidade, unique_percentage_at_least.sql sai."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0, percentual_unico=97.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="cpf", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert (tmp_path / "macros" / "unique_percentage_at_least.sql").exists()

    def test_macro_composite_relationships_nao_gerado_sem_consumidor(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem FK composta referenciando o lote, composite_relationships.sql não sai."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "macros" / "composite_relationships.sql").exists()

    def test_macro_composite_relationships_gerado_com_consumidor(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Com FK composta referenciando tabela do lote, composite_relationships sai."""
        tabela = construir_tabela(
            colunas=[
                construir_coluna(nome="pais_id"),
                construir_coluna(nome="estado_id"),
            ],
            nome_tabela="pedidos",
            nome_escopo="vendas",
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="vendas",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        tabela_estados = construir_tabela(
            colunas=[construir_coluna(nome="id", chave_primaria=True)],
            nome_tabela="estados",
            nome_escopo="vendas",
        )
        banco = construir_banco([tabela, tabela_estados])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert (tmp_path / "macros" / "composite_relationships.sql").exists()

    def test_packages_yml_gerado_por_teste_soft_nulo_sem_restricao_unica(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """packages.yml também sai quando só o teste soft de nulo consome dbt_utils.

        Antes da #90, usa_dbt_utils só considerava restricoes_unicas (#89).
        dbt_utils.not_null_proportion é o segundo consumidor real possível.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=5.0, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert (tmp_path / "packages.yml").exists()


class TestErro:
    """Erro esperado."""

    def test_nome_de_tabela_com_espaco_falha_antes_de_escrever(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Tabela com espaço no nome vira model inválido — Falha, não normalização."""
        tabela = construir_tabela(
            colunas=[construir_coluna()], nome_tabela="order items"
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Falha)
        assert "stg_escopo__order items" in resultado.erro
        assert not (tmp_path / "dbt_project.yml").exists()

    def test_nome_de_escopo_com_hifen_falha_antes_de_escrever(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Escopo com hífen no nome vira model inválido — Falha, não normalização."""
        tabela = construir_tabela(
            colunas=[construir_coluna()], nome_escopo="sales-eu"
        )
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Falha)
        assert "stg_sales-eu__tabela" in resultado.erro
        assert not (tmp_path / "dbt_project.yml").exists()


class TestBorda:
    """Bordas."""

    def test_coluna_com_apostrofo_no_nome_escapa_o_literal_jinja(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Apóstrofo no nome não quebra o literal Jinja de `adapter.quote()`."""
        coluna = construir_coluna(nome="d'agua")
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path / "models" / "staging" / "escopo" / "stg_escopo__tabela.sql"
        ).read_text()
        assert "adapter.quote('d\\'agua')" in sql

    def test_packages_yml_orfao_e_removido_quando_restricao_some(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """packages.yml de execução anterior é removido sem consumidor novo.

        Simula o cenário achado pela banca de revisão: UNIQUE composto existia
        numa execução passada (packages.yml em disco) e foi removido do banco —
        a próxima geração não deve deixar o arquivo órfão pra trás.
        """
        (tmp_path / "packages.yml").write_text("packages: []\n")
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not (tmp_path / "packages.yml").exists()

    def test_amostra_vazia_nao_sugere_unique_ou_not_null_sem_fato_estrutural(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Amostra vazia não sugere unique/not_null com base em zero evidência.

        _metricas_vazias() zera percentual_nulo/percentual_unico pra amostra
        vazia — sem o guard de tamanho_amostra > 0, o Gerador sugeriria
        unique/not_null como se a amostra tivesse confirmado isso (issue #56).
        """
        metrica_vazia = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=0.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="email", metricas=[metrica_vazia])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=0)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "email")
        assert "tests" not in coluna_yaml

    def test_amostra_vazia_com_fato_estrutural_ainda_sugere_teste(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """NOT NULL do schema ainda sugere o teste mesmo sem evidência amostral."""
        metrica_vazia = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=0.0, valores_frequentes=[]
        )
        coluna = construir_coluna(
            nome="email", nao_nulavel=True, metricas=[metrica_vazia]
        )
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=0)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "email")
        assert coluna_yaml["tests"] == ["not_null"]

    def test_array_sem_elemento_reconhecido_nao_recebe_cast(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """ARRAY sem elemento reconhecido é projetado raw, sem '[]' sem tipo."""
        coluna = construir_coluna(
            nome="pontos",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.ARRAY),
            metricas=[],
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        sql = (
            tmp_path / "models" / "staging" / "escopo" / "stg_escopo__tabela.sql"
        ).read_text()
        assert (
            "{{ adapter.quote('pontos') }} as {{ adapter.quote('pontos') }}"
        ) in sql
        assert "CAST" not in sql

    def test_teste_soft_nulo_omitido_com_amostra_abaixo_do_piso(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Amostra abaixo de 100 linhas não sugere o teste soft de nulo."""
        metrica = MetricasBaseColuna(
            percentual_nulo=5.0, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=50)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "telefone")
        assert "tests" not in coluna_yaml

    def test_teste_soft_nulo_no_limite_exato_ainda_dispara(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual_nulo == 10.0 (limite inclusivo) ainda dispara o teste soft."""
        metrica = MetricasBaseColuna(
            percentual_nulo=10.0, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "telefone")
        assert any(
            isinstance(t, dict) and "dbt_utils.not_null_proportion" in t
            for t in coluna_yaml["tests"]
        )

    def test_teste_soft_nulo_acima_do_limite_nao_dispara(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual_nulo acima de 10.0 não dispara nem o teste hard nem o soft."""
        metrica = MetricasBaseColuna(
            percentual_nulo=10.5, percentual_unico=50.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="telefone", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "telefone")
        assert "tests" not in coluna_yaml

    def test_teste_soft_unico_omitido_com_amostra_abaixo_do_piso(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Amostra abaixo de 100 linhas não sugere o teste soft de unicidade."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0, percentual_unico=97.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="cpf", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=50)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "cpf")
        assert "tests" not in coluna_yaml

    def test_teste_soft_unico_abaixo_do_limite_nao_dispara(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual_unico logo abaixo de 95.0 não dispara o teste soft."""
        metrica = MetricasBaseColuna(
            percentual_nulo=20.0, percentual_unico=94.9, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="cpf", metricas=[metrica])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=100)
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        schema = _schema_yml(tmp_path)
        modelo = _modelo(schema, "stg_escopo__tabela")
        coluna_yaml = _coluna(modelo, "cpf")
        assert "tests" not in coluna_yaml

    def test_macros_matches_format_orfaos_sao_removidos(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """macros/matches_format/ de execução anterior é removido sem consumidor.

        Mesmo cenário já validado para packages.yml na #89: formato_detectado
        existia numa execução passada e deixou de existir no lote atual.
        """
        pasta = tmp_path / "macros" / "matches_format"
        pasta.mkdir(parents=True)
        (pasta / "matches_format.sql").write_text("-- execução anterior")
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not pasta.exists()

    def test_macros_cast_type_orfaos_sao_removidos(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """macros/cast_type/ de execução anterior é removido sem consumidor."""
        pasta = tmp_path / "macros" / "cast_type"
        pasta.mkdir(parents=True)
        (pasta / "cast_type.sql").write_text("-- execução anterior")
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not pasta.exists()

    def test_macro_unique_percentage_orfao_e_removido(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """unique_percentage_at_least.sql de execução anterior some sem uso."""
        caminho = tmp_path / "macros" / "unique_percentage_at_least.sql"
        caminho.parent.mkdir(parents=True)
        caminho.write_text("-- execução anterior")
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not caminho.exists()

    def test_macro_composite_relationships_orfao_e_removido(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """composite_relationships.sql de execução anterior some sem consumidor."""
        caminho = tmp_path / "macros" / "composite_relationships.sql"
        caminho.parent.mkdir(parents=True)
        caminho.write_text("-- execução anterior")
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorDbt()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert not caminho.exists()

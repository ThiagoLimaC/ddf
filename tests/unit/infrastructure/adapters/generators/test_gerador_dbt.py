"""Testes de GeradorDbt: caminho feliz, erro de disco, bordas e determinismo."""

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import ddf.infrastructure.adapters.generators.gerador_dbt as gerador_dbt_modulo
from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    TabelaAnalisada,
)
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.analyzers.detector_de_formato import _REGEXES
from ddf.infrastructure.adapters.generators.gerador_dbt import GeradorDbt

_CAMINHO_MACRO_MATCHES_FORMAT = (
    Path(gerador_dbt_modulo.__file__).parent
    / "templates"
    / "macros"
    / "matches_format"
    / "matches_format.sql"
)


def _schema_yml(destino: Path, escopo: str = "escopo") -> dict[str, Any]:
    conteudo = (destino / "models" / "staging" / escopo / "schema.yml").read_text()
    resultado: dict[str, Any] = yaml.safe_load(conteudo)
    return resultado


def _modelo(schema: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(m for m in schema["models"] if m["name"] == nome)


def _coluna(modelo: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(c for c in modelo["columns"] if c["name"] == nome)


def test_caminho_feliz_gera_artefatos_por_escopo(
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
        referencia=ReferenciaDeColuna(
            nome_escopo="rh", nome_tabela="perfis", nome_coluna="id"
        ),
        metricas=[metrica_nao_nula],
    )
    tabela_clientes = construir_tabela(
        colunas=[coluna_id, coluna_email, coluna_status, coluna_perfil_id],
        nome_tabela="clientes",
        nome_escopo="vendas",
    )
    coluna_perfil_id_pk = construir_coluna(
        nome="id",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10, escala=2),
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
    assert linhas_sql[1] == "    CAST(id AS INTEGER) as id,"
    assert linhas_sql[2] == "    CAST(email AS VARCHAR(255)) as email,"
    assert linhas_sql[3] == "    CAST(status AS VARCHAR(10)) as status,"
    assert linhas_sql[4] == "    CAST(perfil_id AS INTEGER) as perfil_id"  # sem vírgula
    assert linhas_sql[5] == "from {{ source('vendas', 'clientes') }}"

    sql_perfis = (
        tmp_path / "models" / "staging" / "rh" / "stg_rh__perfis.sql"
    ).read_text()
    assert "CAST(id AS NUMERIC(10,2)) as id" in sql_perfis

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
    assert "not_null" in coluna_email_yaml["tests"]

    coluna_status_yaml = _coluna(modelo_clientes, "status")
    testes_status = coluna_status_yaml["tests"]
    accepted = next(t for t in testes_status if isinstance(t, dict))
    assert accepted["accepted_values"]["values"] == ["ativo", "inativo"]
    assert accepted["accepted_values"]["config"]["severity"] == "warn"

    coluna_perfil_yaml = _coluna(modelo_clientes, "perfil_id")
    testes_perfil = coluna_perfil_yaml["tests"]
    relacionamento = next(t for t in testes_perfil if isinstance(t, dict))
    assert relacionamento["relationships"]["to"] == "ref('stg_rh__perfis')"
    assert relacionamento["relationships"]["field"] == "id"


def test_dbt_project_registra_generated_at(
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
    datetime.fromisoformat(projeto["meta"]["generated_at"])  # ValueError se malformado


def test_readme_lista_escopos_e_tabelas_do_lote(
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
    assert "- `clientes` → `models/staging/vendas/stg_vendas__clientes.sql`" in readme
    assert "- `perfis` → `models/staging/rh/stg_rh__perfis.sql`" in readme


def test_packages_yml_nao_e_gerado_sem_unique_composto(
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


def test_packages_yml_orfao_e_removido_quando_restricao_some(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Borda: packages.yml de execução anterior é removido sem consumidor novo.

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


def test_falha_ao_nao_conseguir_escrever_em_disco(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Destino onde não é possível criar o dbt_project.yml retorna Falha com o path."""
    obstaculo = tmp_path / "dbt_project.yml"
    obstaculo.mkdir()
    (obstaculo / "arquivo_dentro_do_diretorio").write_text("bloqueia o write_text")

    tabela = construir_tabela(colunas=[construir_coluna()])
    banco = construir_banco([tabela])

    resultado = GeradorDbt()(banco, tmp_path)

    assert isinstance(resultado, Falha)
    assert str(obstaculo) in resultado.erro


def test_coluna_sem_metrica_e_sem_fato_estrutural_nao_sugere_teste(
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


def test_amostra_vazia_nao_sugere_unique_ou_not_null_sem_fato_estrutural(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Borda: amostra vazia não sugere unique/not_null com base em zero evidência.

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
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Borda: NOT NULL do schema ainda sugere o teste mesmo sem evidência amostral."""
    metrica_vazia = MetricasBaseColuna(
        percentual_nulo=0.0, percentual_unico=0.0, valores_frequentes=[]
    )
    coluna = construir_coluna(nome="email", nao_nulavel=True, metricas=[metrica_vazia])
    tabela = construir_tabela(colunas=[coluna], tamanho_amostra=0)
    banco = construir_banco([tabela])

    resultado = GeradorDbt()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    schema = _schema_yml(tmp_path)
    modelo = _modelo(schema, "stg_escopo__tabela")
    coluna_yaml = _coluna(modelo, "email")
    assert coluna_yaml["tests"] == ["not_null"]


def test_fk_fora_do_lote_emite_aviso_e_omite_relationships(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """FK apontando para tabela fora do BancoAnalisado gera Aviso, sem relationships."""
    coluna_fk = construir_coluna(
        nome="funcionario_id",
        chave_estrangeira=True,
        referencia=ReferenciaDeColuna(
            nome_escopo="rh", nome_tabela="funcionarios", nome_coluna="id"
        ),
        metricas=[],
    )
    tabela = construir_tabela(
        colunas=[coluna_fk], nome_tabela="pedidos", nome_escopo="vendas"
    )
    banco = construir_banco([tabela])

    resultado = GeradorDbt()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    assert len(resultado.avisos) == 1
    assert "rh.funcionarios" in resultado.avisos[0].mensagem

    schema = _schema_yml(tmp_path, "vendas")
    modelo = _modelo(schema, "stg_vendas__pedidos")
    coluna_yaml = _coluna(modelo, "funcionario_id")
    assert "tests" not in coluna_yaml


def test_accepted_values_omitido_quando_top10_cobre_pouco_da_amostra(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Top-10 cobrindo pouco da amostra não sugere accepted_values, mesmo categórica.

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
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Coluna com muitos nulos, mas exaustiva sobre os não-nulos, ainda sugere o teste.

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


def test_coluna_unknown_nao_recebe_cast(
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
    assert "spatiallocation as spatiallocation" in sql
    assert "CAST" not in sql


def test_array_com_elemento_reconhecido_recebe_cast_de_array(
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
    assert "CAST(tags AS INTEGER[])" in sql


def test_array_sem_elemento_reconhecido_nao_recebe_cast(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Borda: ARRAY sem elemento reconhecido é projetado raw, sem '[]' sem tipo."""
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
    assert "pontos as pontos" in sql
    assert "CAST" not in sql


def test_geracao_e_deterministica(
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
        assert (destino_a / relativo).read_text() == (destino_b / relativo).read_text()

    projeto_a = yaml.safe_load((destino_a / "dbt_project.yml").read_text())
    projeto_b = yaml.safe_load((destino_b / "dbt_project.yml").read_text())
    assert "generated_at" in projeto_a["meta"]
    del projeto_a["meta"]["generated_at"]
    del projeto_b["meta"]["generated_at"]
    assert projeto_a == projeto_b


def test_macro_matches_format_cobre_todos_os_formatos_do_detector() -> None:
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

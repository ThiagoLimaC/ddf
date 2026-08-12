"""dbt parse/compile real sobre o artefato gerado (issue #140, achado 5).

Fecha a lacuna que sobreviveu a #14/#77/#89/#90/#95/#105/#132: os testes do
`GeradorDbt` afirmavam sobre a string do SQL/YAML gerado, nunca sobre
executabilidade real. Aqui o pipeline real (`Extrator` -> `SobrescritaDeTabela`
-> `iniciar_contexto` -> `GeradorDbt`) roda contra Postgres/MariaDB reais
(testcontainers), e o projeto gerado é compilado pelo dbt de verdade — em
processo (`dbtRunner`) para Postgres, via subprocess num venv isolado
(`dbt_mariadb_bin`, ver `conftest.py`) para MariaDB.
"""

import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from dbt.cli.main import dbtRunner

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    TabelaAnalisada,
    iniciar_contexto,
)
from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import BancoCurado
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)
from ddf.infrastructure.adapters.generators.dbt.gerador_dbt import GeradorDbt
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)


def _extrair_e_analisar(
    extrator: ExtratorPostgres | ExtratorMariaDB,
    escopo: str,
    tabela: str,
    tmp_path: Path,
) -> TabelaAnalisada:
    """Roda o pipeline real Extrator -> SobrescritaDeTabela -> iniciar_contexto.

    Sem Analisador — o `GeradorDbt` não precisa de `MetricasBaseColuna` pra
    montar CAST/quoting, e este teste valida executabilidade do SQL/YAML
    gerado, não as sugestões de teste dependentes de métrica.
    """
    resultado_extracao = extrator.extrair_tabela(escopo, tabela)
    assert isinstance(resultado_extracao, Sucesso), resultado_extracao
    sobrescrita = SobrescritaDeTabela(tmp_path / "overrides")
    resultado_curadoria = sobrescrita(resultado_extracao.valor)
    assert isinstance(resultado_curadoria, Sucesso), resultado_curadoria
    contexto = iniciar_contexto(BancoCurado(tabelas=[resultado_curadoria.valor]))
    return contexto.analisado.tabelas[0]


def _profiles_yml_postgres(dsn_postgres: str) -> dict[str, Any]:
    partes = urlparse(dsn_postgres)
    return {
        "ddf_staging": {
            "target": "dev",
            "outputs": {
                "dev": {
                    "type": "postgres",
                    "host": partes.hostname,
                    "port": partes.port,
                    "user": partes.username,
                    "password": partes.password,
                    "dbname": (partes.path or "/postgres").lstrip("/"),
                    "schema": "public",
                }
            },
        }
    }


def _profiles_yml_mariadb(conexao_mariadb: tuple[str, int, str, str]) -> dict[str, Any]:
    host, port, user, password = conexao_mariadb
    return {
        "ddf_staging": {
            "target": "dev",
            "outputs": {
                "dev": {
                    "type": "mariadb",
                    "server": host,
                    "port": port,
                    "username": user,
                    "password": password,
                    "schema": "verificacao",
                }
            },
        }
    }


def _escrever_profiles(diretorio: Path, conteudo: dict[str, Any]) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / "profiles.yml").write_text(yaml.safe_dump(conteudo))


class TestFeliz:
    """Caminho feliz."""

    def test_projeto_gerado_a_partir_do_postgres_real_compila(
        self,
        dsn_postgres: str,
        configuracao: ConfiguracaoDeExtracao,
        tmp_path: Path,
    ) -> None:
        """Projeto gerado a partir de extração Postgres real compila via dbtRunner."""
        extrator = ExtratorPostgres(dsn=dsn_postgres, configuracao=configuracao)
        tabela = _extrair_e_analisar(extrator, "verificacao", "diversos", tmp_path)
        banco = BancoAnalisado(tabelas=[tabela])

        destino = tmp_path / "projeto"
        resultado_geracao = GeradorDbt()(banco, destino)
        assert isinstance(resultado_geracao, Sucesso), resultado_geracao

        profiles_dir = tmp_path / "profiles"
        _escrever_profiles(profiles_dir, _profiles_yml_postgres(dsn_postgres))

        resultado = dbtRunner().invoke(
            [
                "compile",
                "--project-dir",
                str(destino),
                "--profiles-dir",
                str(profiles_dir),
            ]
        )

        assert resultado.success, resultado.exception

    def test_projeto_gerado_a_partir_do_mariadb_real_compila(
        self,
        conexao_mariadb: tuple[str, int, str, str],
        configuracao: ConfiguracaoDeExtracao,
        dbt_mariadb_bin: Path,
        tmp_path: Path,
    ) -> None:
        """Projeto gerado a partir de extração MariaDB real compila via subprocess.

        Confirma (ou corrige, se falhar) a tabela de dispatch de `cast_type`
        validada empiricamente pela banca da issue #140 — inclusive
        `DATETIME(3)` (precisão fracionária real capturada na extração) e o
        quoting de `order`/`left` via `adapter.quote()`.
        """
        host, port, user, password = conexao_mariadb
        extrator = ExtratorMariaDB(
            host=host,
            port=port,
            user=user,
            password=password,
            configuracao=configuracao,
        )
        tabela = _extrair_e_analisar(extrator, "verificacao", "diversos", tmp_path)
        banco = BancoAnalisado(tabelas=[tabela])

        destino = tmp_path / "projeto"
        resultado_geracao = GeradorDbt()(banco, destino)
        assert isinstance(resultado_geracao, Sucesso), resultado_geracao

        profiles_dir = tmp_path / "profiles"
        _escrever_profiles(profiles_dir, _profiles_yml_mariadb(conexao_mariadb))

        processo = subprocess.run(
            [
                str(dbt_mariadb_bin),
                "compile",
                "--project-dir",
                str(destino),
                "--profiles-dir",
                str(profiles_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert processo.returncode == 0, processo.stdout + processo.stderr


class TestErro:
    """Erro esperado."""

    def _tabela_numeric_sem_precisao(self) -> TabelaAnalisada:
        coluna = ColunaAnalisada(
            nome="valor",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.NUMERIC),
        )
        return TabelaAnalisada(
            nome_tabela="numeric_sem_precisao",
            nome_escopo="verificacao",
            colunas=[coluna],
            total_linhas=1,
            metadados_amostra=MetadadosDeAmostra(
                estrategia="percentual_de_linhas", tamanho_amostra=1, total_linhas=1
            ),
        )

    def test_numeric_sem_precisao_falha_no_compile_do_mariadb(
        self,
        conexao_mariadb: tuple[str, int, str, str],
        dbt_mariadb_bin: Path,
        tmp_path: Path,
    ) -> None:
        """NUMERIC sem precisão/escala falha explícito no dbt compile do MariaDB.

        Em vez de gerar `CAST(x AS DECIMAL)` sem parâmetros — que trunca/clipa
        em silêncio no MariaDB real (achado do engenheiro de dados) — o macro
        `mariadb__cast_type` levanta `raise_compiler_error`.
        """
        banco = BancoAnalisado(tabelas=[self._tabela_numeric_sem_precisao()])
        destino = tmp_path / "projeto"
        resultado_geracao = GeradorDbt()(banco, destino)
        assert isinstance(resultado_geracao, Sucesso), resultado_geracao

        profiles_dir = tmp_path / "profiles"
        _escrever_profiles(profiles_dir, _profiles_yml_mariadb(conexao_mariadb))

        processo = subprocess.run(
            [
                str(dbt_mariadb_bin),
                "compile",
                "--project-dir",
                str(destino),
                "--profiles-dir",
                str(profiles_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert processo.returncode != 0
        assert "NUMERIC sem precisão/escala" in processo.stdout + processo.stderr

    def test_numeric_sem_precisao_compila_normalmente_no_postgres(
        self,
        dsn_postgres: str,
        tmp_path: Path,
    ) -> None:
        """O mesmo caso compila normal no Postgres — NUMERIC bare é seguro lá."""
        banco = BancoAnalisado(tabelas=[self._tabela_numeric_sem_precisao()])
        destino = tmp_path / "projeto"
        resultado_geracao = GeradorDbt()(banco, destino)
        assert isinstance(resultado_geracao, Sucesso), resultado_geracao

        profiles_dir = tmp_path / "profiles"
        _escrever_profiles(profiles_dir, _profiles_yml_postgres(dsn_postgres))

        resultado = dbtRunner().invoke(
            [
                "compile",
                "--project-dir",
                str(destino),
                "--profiles-dir",
                str(profiles_dir),
            ]
        )

        assert resultado.success, resultado.exception

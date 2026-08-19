"""Fixtures do teste de dbt parse/compile real (issue #140, achado 5).

`dsn_postgres`/`conexao_mariadb` seguem exatamente o padrão já usado em
`tests/integration/extractors/<motor>/conftest.py` — schema próprio
(`verificacao`) com os tipos/identificadores validados empiricamente pela
banca da issue #140 (BIGINT, TEXT sem tamanho, NUMERIC(p,s), BOOLEAN, JSON,
DOUBLE PRECISION/DOUBLE, REAL/FLOAT, TIME, TIMESTAMP/DATETIME e TIME com
precisão fracionária, colunas com nome de palavra reservada) mais uma
segunda tabela (`pai`/`filho_fk_composta`) com FK composta real, pra
exercitar `composite_relationships` via `dbt compile` de verdade — não só
por asserção de string em teste unitário (segunda rodada de banca da
#140). `TIME WITH TIME ZONE` não tem equivalente no MariaDB, por isso só
existe na tabela Postgres; o lado MariaDB desse dispatch é coberto por
tabela sintética no teste (`_tabela_time_com_timezone`).

`dbt_mariadb_bin` é o mecanismo à parte para o lado MariaDB: `dbt-mysql`
(único adapter dbt com suporte a `type: mariadb`) trava em `dbt-core<=1.7`,
que não roda em Python 3.12 (mínimo do projeto) — nunca instalado como
dependência normal (conflitaria com `mypy>=2.1.0`, que exige
`pathspec>=1.0.0`; `dbt-core` 1.7 exige `pathspec<0.12`, faixas mutuamente
exclusivas). Provisiona um venv Python 3.11 isolado, cacheado entre
execuções, nunca tocando o venv principal do projeto.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg2
import pymysql
import pytest
from testcontainers.mysql import MySqlContainer
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)

_SETUP_SQL_POSTGRES = """
    CREATE SCHEMA verificacao;

    CREATE TABLE verificacao.diversos (
        id BIGINT PRIMARY KEY,
        descricao TEXT NOT NULL,
        preco NUMERIC(10, 2) NOT NULL,
        ativo BOOLEAN NOT NULL,
        dados JSON NOT NULL,
        medida DOUBLE PRECISION NOT NULL,
        nota REAL NOT NULL,
        criado_em TIMESTAMP(3) WITH TIME ZONE NOT NULL,
        hora TIME NOT NULL,
        hora_tz TIME WITH TIME ZONE NOT NULL,
        "order" INTEGER NOT NULL,
        "left" INTEGER NOT NULL
    );

    INSERT INTO verificacao.diversos
        (id, descricao, preco, ativo, dados, medida, nota, criado_em, hora,
         hora_tz, "order", "left")
    VALUES
        (1, 'a', 10.50, true, '{"a": 1}', 1.5, 3.5, now(), '10:00:00',
         '10:00:00+00', 1, 1),
        (2, 'b', 20.00, false, '{"b": 2}', 2.5, 4.5, now(), '11:00:00',
         '11:00:00+00', 2, 2);

    ANALYZE verificacao.diversos;

    CREATE TABLE verificacao.pai (
        chave_a INTEGER NOT NULL,
        chave_b INTEGER NOT NULL,
        PRIMARY KEY (chave_a, chave_b)
    );

    INSERT INTO verificacao.pai (chave_a, chave_b) VALUES (1, 1), (2, 2);

    CREATE TABLE verificacao.filho_fk_composta (
        id BIGINT PRIMARY KEY,
        ref_a INTEGER NOT NULL,
        ref_b INTEGER NOT NULL,
        FOREIGN KEY (ref_a, ref_b) REFERENCES verificacao.pai (chave_a, chave_b)
    );

    INSERT INTO verificacao.filho_fk_composta (id, ref_a, ref_b)
    VALUES (1, 1, 1), (2, 2, 2);

    ANALYZE verificacao.pai;
    ANALYZE verificacao.filho_fk_composta;
"""

_SETUP_STATEMENTS_MARIADB = [
    # "verificacao" já existe — criada pelo dbname= do MySqlContainer abaixo.
    """
    CREATE TABLE verificacao.diversos (
        id BIGINT PRIMARY KEY,
        descricao TEXT NOT NULL,
        preco DECIMAL(10, 2) NOT NULL,
        ativo TINYINT(1) NOT NULL,
        dados JSON NOT NULL,
        medida DOUBLE NOT NULL,
        nota FLOAT NOT NULL,
        criado_em DATETIME(3) NOT NULL,
        hora TIME NOT NULL,
        `order` INTEGER NOT NULL,
        `left` INTEGER NOT NULL
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO verificacao.diversos
        (id, descricao, preco, ativo, dados, medida, nota, criado_em, hora,
         `order`, `left`)
    VALUES
        (1, 'a', 10.50, 1, '{"a": 1}', 1.5, 3.5, NOW(3), '10:00:00', 1, 1),
        (2, 'b', 20.00, 0, '{"b": 2}', 2.5, 4.5, NOW(3), '11:00:00', 2, 2)
    """,
    """
    CREATE TABLE verificacao.pai (
        chave_a INT NOT NULL,
        chave_b INT NOT NULL,
        PRIMARY KEY (chave_a, chave_b)
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO verificacao.pai (chave_a, chave_b) VALUES (1, 1), (2, 2)
    """,
    """
    CREATE TABLE verificacao.filho_fk_composta (
        id BIGINT PRIMARY KEY,
        ref_a INT NOT NULL,
        ref_b INT NOT NULL,
        FOREIGN KEY (ref_a, ref_b) REFERENCES verificacao.pai (chave_a, chave_b)
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO verificacao.filho_fk_composta (id, ref_a, ref_b)
    VALUES (1, 1, 1), (2, 2, 2)
    """,
]

_VENV_MARIADB = Path.home() / ".cache" / "ddf-tests" / "dbt-mariadb-venv-py311"


@pytest.fixture(scope="session")
def dsn_postgres() -> Iterator[str]:
    """Sobe um Postgres descartável via testcontainers e semeia o schema de teste."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_SETUP_SQL_POSTGRES)
        yield url


@pytest.fixture(scope="session")
def conexao_mariadb() -> Iterator[tuple[str, int, str, str]]:
    """Sobe um MariaDB descartável via testcontainers e semeia o schema de teste.

    Retorna (host, port, user, password) — mesmo formato de
    `tests/integration/extractors/mariadb/conftest.py`.
    """
    with MySqlContainer(
        "mariadb:11", username="root", root_password="test", dbname="verificacao"
    ) as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(container.port))
        conexao_raiz = pymysql.connect(
            host=host, port=port, user="root", password="test", autocommit=True
        )
        try:
            with conexao_raiz.cursor() as cursor:
                for comando in _SETUP_STATEMENTS_MARIADB:
                    cursor.execute(comando)
        finally:
            conexao_raiz.close()
        yield (host, port, "root", "test")


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """ConfiguracaoDeExtracao com percentual=100 — amostra determinística nos testes."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=100))


@pytest.fixture(scope="session")
def dbt_mariadb_bin() -> Path:
    """Provisiona (ou reaproveita) o venv Python 3.11 isolado com dbt-core+dbt-mysql."""
    executavel = _VENV_MARIADB / "bin" / "dbt"
    if not executavel.exists():
        _VENV_MARIADB.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["uv", "venv", "--python", "3.11", str(_VENV_MARIADB)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(_VENV_MARIADB / "bin" / "python"),
                "dbt-core==1.7.19",
                "dbt-mysql",
            ],
            check=True,
            capture_output=True,
        )
    return executavel

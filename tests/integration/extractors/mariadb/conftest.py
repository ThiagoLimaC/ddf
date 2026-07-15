"""Fixtures de integração de ExtratorMariaDB — MariaDB real via testcontainers."""

from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)

_SETUP_STATEMENTS = [
    "CREATE DATABASE vazio",
    "CREATE DATABASE pessoa",
    "CREATE DATABASE rh",
    """
    CREATE TABLE vendas.clientes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(100) NOT NULL,
        ativo TINYINT(1) NOT NULL DEFAULT 1,
        status ENUM('ativo', 'inativo') NOT NULL DEFAULT 'ativo',
        criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE vendas.pedidos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cliente_id INT NOT NULL,
        valor DECIMAL(10, 2) NOT NULL,
        FOREIGN KEY (cliente_id) REFERENCES vendas.clientes(id)
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO vendas.clientes (nome, ativo) VALUES
        ('ana', 1), ('bia', 1), ('caio', 0)
    """,
    """
    INSERT INTO vendas.pedidos (cliente_id, valor) VALUES
        (1, 10.50), (1, 20.00), (2, 5.25)
    """,
    """
    CREATE TABLE pessoa.pessoa (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(100) NOT NULL
    ) ENGINE=InnoDB
    """,
    # FK cross-database (rh.funcionario -> pessoa.pessoa): prova que o escopo
    # de destino da FK é capturado mesmo quando difere do escopo de origem,
    # mesmo teste que provou o bug da FK cross-schema no Postgres (issue #9).
    """
    CREATE TABLE rh.funcionario (
        id INT AUTO_INCREMENT PRIMARY KEY,
        pessoa_id INT NOT NULL,
        cargo VARCHAR(100) NOT NULL,
        FOREIGN KEY (pessoa_id) REFERENCES pessoa.pessoa(id)
    ) ENGINE=InnoDB
    """,
    "INSERT INTO pessoa.pessoa (nome) VALUES ('duda'), ('elias')",
    "INSERT INTO rh.funcionario (pessoa_id, cargo) VALUES (1, 'engenheira')",
    "ANALYZE TABLE vendas.clientes",
    "ANALYZE TABLE vendas.pedidos",
    "ANALYZE TABLE pessoa.pessoa",
    "ANALYZE TABLE rh.funcionario",
]


@pytest.fixture(scope="session")
def conexao() -> Iterator[tuple[str, int, str, str]]:
    """Sobe um MariaDB descartável via testcontainers e semeia o schema de teste.

    Retorna (host, port, user, password) — sem NamedTuple próprio pra evitar
    import cruzado entre conftest.py e os módulos de teste (tests/ não é um
    pacote Python instalável).
    """
    with MySqlContainer(
        "mariadb:11", username="root", root_password="test", dbname="vendas"
    ) as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(container.port))
        conexao_raiz = pymysql.connect(
            host=host, port=port, user="root", password="test", autocommit=True
        )
        try:
            with conexao_raiz.cursor() as cursor:
                for comando in _SETUP_STATEMENTS:
                    cursor.execute(comando)
        finally:
            conexao_raiz.close()
        yield (host, port, "root", "test")


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """ConfiguracaoDeExtracao com percentual=100 — amostra determinística nos testes."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=100))

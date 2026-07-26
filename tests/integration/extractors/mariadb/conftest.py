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
    "CREATE DATABASE restricoes",
    # "pedidos" e "clientes" têm UNIQUE KEY com o MESMO NOME ("email") no
    # MESMO database — reproduz a colisão de nome de constraint entre
    # tabelas (achado da banca nesta issue: nomes de constraint no
    # MySQL/MariaDB são escopados por tabela, não por schema). Sem o filtro
    # AND kcu.table_name = %s, extrair "pedidos" veria as 2 linhas (de
    # "pedidos" e de "clientes") sob o mesmo constraint_name e classificaria
    # "email" como não-única por acidente.
    # "metadados" é JSON nas duas tabelas — mesma coluna, mesmo nome de
    # constraint CHECK auto-gerado (issue #56), reproduzindo pra JSON o
    # mesmo cenário de colisão de nome entre tabelas já usado acima pra
    # UNIQUE ("email"): sem o cruzamento com as colunas reais da tabela em
    # _colunas_json_de_check_clauses, o JOIN sem TABLE_NAME em
    # CHECK_CONSTRAINTS faria "pedidos" enxergar o CHECK_CLAUSE de
    # "clientes" (e vice-versa) — mas como os dois têm coluna "metadados",
    # o resultado seria o mesmo por coincidência; a defesa real está
    # provada no teste unit com nomes de coluna diferentes.
    """
    CREATE TABLE restricoes.pedidos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(150) NOT NULL,
        apelido VARCHAR(50),
        metadados JSON,
        UNIQUE KEY email (email)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE restricoes.clientes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(150) NOT NULL,
        metadados JSON,
        UNIQUE KEY email (email)
    ) ENGINE=InnoDB
    """,
    "CREATE UNIQUE INDEX idx_pedidos_apelido_unico ON restricoes.pedidos (apelido)",
    """
    CREATE TABLE restricoes.enderecos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        pais CHAR(2) NOT NULL,
        cep CHAR(9) NOT NULL,
        UNIQUE KEY uk_pais_cep (pais, cep)
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO restricoes.pedidos (email, apelido, metadados) VALUES
        ('ana@x.com', 'aninha', '{"origem": "site"}')
    """,
    "INSERT INTO restricoes.clientes (email, metadados) VALUES ('bia@x.com', '{}')",
    "INSERT INTO restricoes.enderecos (pais, cep) VALUES ('BR', '01000-000')",
    "ANALYZE TABLE restricoes.pedidos",
    "ANALYZE TABLE restricoes.clientes",
    "ANALYZE TABLE restricoes.enderecos",
    # Massa suficiente pra reprodutibilidade de seed fazer sentido
    # estatisticamente (issue #76). seq_1_to_500 é a engine SEQUENCE nativa
    # do MariaDB — evita tabela auxiliar só pra gerar linhas.
    "CREATE DATABASE reprodutibilidade",
    """
    CREATE TABLE reprodutibilidade.itens (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(50) NOT NULL
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO reprodutibilidade.itens (nome)
        SELECT CONCAT('item_', seq) FROM reprodutibilidade.seq_1_to_500
    """,
    "ANALYZE TABLE reprodutibilidade.itens",
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

"""Fixtures de integração de ExtratorMariaDB — MariaDB real via testcontainers."""

from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
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
    # FK composta (2 colunas, issue #95): prova que o agrupamento por
    # CONSTRAINT_NAME não mistura colunas de constraints diferentes —
    # mesma fixture do ExtratorPostgres (geografia.pais/filial).
    "CREATE DATABASE geografia",
    """
    CREATE TABLE geografia.pais (
        codigo CHAR(2) NOT NULL,
        estado CHAR(2) NOT NULL,
        PRIMARY KEY (codigo, estado)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE geografia.filial (
        id INT AUTO_INCREMENT PRIMARY KEY,
        pais_codigo CHAR(2) NOT NULL,
        pais_estado CHAR(2) NOT NULL,
        FOREIGN KEY (pais_codigo, pais_estado)
            REFERENCES geografia.pais(codigo, estado)
    ) ENGINE=InnoDB
    """,
    "INSERT INTO geografia.pais (codigo, estado) VALUES ('BR', 'SP'), ('BR', 'RJ')",
    "INSERT INTO geografia.filial (pais_codigo, pais_estado) VALUES ('BR', 'SP')",
    "ANALYZE TABLE geografia.pais",
    "ANALYZE TABLE geografia.filial",
    "CREATE DATABASE restricoes",
    # "pedidos" e "clientes" têm UNIQUE KEY com o MESMO NOME ("email") no
    # MESMO database — reproduz a colisão de nome de constraint entre
    # tabelas (nomes de constraint no MySQL/MariaDB são escopados por
    # tabela, não por schema, ver `_COLUNAS_UNICAS_SQL`). Também têm coluna
    # "metadados" JSON nas duas — não prova sozinho a atribuição correta por
    # tabela (as duas colunas têm o mesmo nome, então o resultado seria
    # igual mesmo se a atribuição vazasse entre tabelas); a colisão de CHECK
    # com atribuição observável está em "relatorios"/"contadores" abaixo.
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
    # "relatorios" e "contadores" têm CHECK constraint com o MESMO NOME
    # ("conteudo") e a MESMA coluna ("conteudo") no MESMO database, mas só
    # "relatorios.conteudo" é JSON de verdade — "contadores.conteudo" é
    # INTEGER com um CHECK aritmético não relacionado a JSON, batizado com o
    # mesmo nome de propósito. Reproduz o cenário que o teste unit
    # equivalente cobre mockado (mesmo nome de coluna nas duas tabelas
    # evita que o cruzamento com nomes_colunas_reais mascare o bug por
    # coincidência — ver comentário acima sobre "pedidos"/"clientes") contra
    # MariaDB real: sem o TABLE_NAME nativo de information_schema.
    # check_constraints, "contadores.conteudo" seria reclassificado como
    # JSON por acidente.
    """
    CREATE TABLE restricoes.relatorios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        conteudo JSON
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE restricoes.contadores (
        id INT AUTO_INCREMENT PRIMARY KEY,
        conteudo INT NOT NULL,
        CONSTRAINT conteudo CHECK (conteudo >= 0)
    ) ENGINE=InnoDB
    """,
    """
    INSERT INTO restricoes.pedidos (email, apelido, metadados) VALUES
        ('ana@x.com', 'aninha', '{"origem": "site"}')
    """,
    "INSERT INTO restricoes.clientes (email, metadados) VALUES ('bia@x.com', '{}')",
    "INSERT INTO restricoes.enderecos (pais, cep) VALUES ('BR', '01000-000')",
    "INSERT INTO restricoes.relatorios (conteudo) VALUES ('{\"ok\": true}')",
    "INSERT INTO restricoes.contadores (conteudo) VALUES (3)",
    "ANALYZE TABLE restricoes.pedidos",
    "ANALYZE TABLE restricoes.clientes",
    "ANALYZE TABLE restricoes.enderecos",
    "ANALYZE TABLE restricoes.relatorios",
    "ANALYZE TABLE restricoes.contadores",
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

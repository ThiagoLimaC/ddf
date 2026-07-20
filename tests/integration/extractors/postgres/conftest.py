"""Fixtures de integração de ExtratorPostgres — Postgres real via testcontainers."""

from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)

_SETUP_SQL = """
    CREATE SCHEMA vazio;
    CREATE SCHEMA pessoa;
    CREATE SCHEMA rh;
    CREATE SCHEMA geografia;

    CREATE TABLE public.clientes (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(100) NOT NULL,
        criado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
    );

    CREATE TABLE public.pedidos (
        id SERIAL PRIMARY KEY,
        cliente_id INTEGER NOT NULL REFERENCES public.clientes(id),
        valor NUMERIC(10, 2) NOT NULL
    );

    INSERT INTO public.clientes (nome) VALUES ('ana'), ('bia'), ('caio');
    INSERT INTO public.pedidos (cliente_id, valor)
        VALUES (1, 10.50), (1, 20.00), (2, 5.25);

    ANALYZE public.clientes;
    ANALYZE public.pedidos;

    -- FK cross-schema (rh.funcionario -> pessoa.pessoa): prova que o escopo
    -- de destino da FK é capturado mesmo quando difere do escopo de origem.
    CREATE TABLE pessoa.pessoa (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(100) NOT NULL
    );

    CREATE TABLE rh.funcionario (
        id SERIAL PRIMARY KEY,
        pessoa_id INTEGER NOT NULL REFERENCES pessoa.pessoa(id),
        cargo VARCHAR(100) NOT NULL
    );

    INSERT INTO pessoa.pessoa (nome) VALUES ('duda'), ('elias');
    INSERT INTO rh.funcionario (pessoa_id, cargo) VALUES (1, 'engenheira');

    ANALYZE pessoa.pessoa;
    ANALYZE rh.funcionario;

    -- FK composta (2 colunas): prova que o pareamento coluna-local <->
    -- coluna-referenciada não vira produto cartesiano (bug encontrado na
    -- revisão da #35, pré-existente desde a #9). Schema próprio (não
    -- public/pessoa/rh) pra não afetar os testes que já fixam a lista de
    -- tabelas/escopos existentes.
    CREATE TABLE geografia.pais (
        codigo CHAR(2) NOT NULL,
        estado CHAR(2) NOT NULL,
        PRIMARY KEY (codigo, estado)
    );

    CREATE TABLE geografia.filial (
        id SERIAL PRIMARY KEY,
        pais_codigo CHAR(2) NOT NULL,
        pais_estado CHAR(2) NOT NULL,
        FOREIGN KEY (pais_codigo, pais_estado)
            REFERENCES geografia.pais(codigo, estado)
    );

    INSERT INTO geografia.pais (codigo, estado) VALUES ('BR', 'SP'), ('BR', 'RJ');
    INSERT INTO geografia.filial (pais_codigo, pais_estado) VALUES ('BR', 'SP');

    ANALYZE geografia.pais;
    ANALYZE geografia.filial;

    -- Restrições reais do schema (issue #44: NOT NULL/UNIQUE além de PK/FK).
    -- "apelido" fica sem UNIQUE constraint nomeada — só um CREATE UNIQUE
    -- INDEX solto, pra provar que a captura via pg_index cobre esse caso,
    -- que information_schema.table_constraints (usado pra PK/FK) não pega.
    CREATE SCHEMA restricoes;

    CREATE TABLE restricoes.contas (
        id SERIAL PRIMARY KEY,
        email VARCHAR(150) NOT NULL UNIQUE,
        apelido VARCHAR(50)
    );
    CREATE UNIQUE INDEX idx_contas_apelido_unico ON restricoes.contas (apelido);

    CREATE TABLE restricoes.enderecos (
        id SERIAL PRIMARY KEY,
        pais CHAR(2) NOT NULL,
        cep CHAR(9) NOT NULL,
        UNIQUE (pais, cep)
    );

    INSERT INTO restricoes.contas (email, apelido) VALUES ('ana@x.com', 'aninha');
    INSERT INTO restricoes.enderecos (pais, cep) VALUES ('BR', '01000-000');

    ANALYZE restricoes.contas;
    ANALYZE restricoes.enderecos;
"""


@pytest.fixture(scope="session")
def dsn() -> Iterator[str]:
    """Sobe um Postgres descartável via testcontainers e semeia o schema de teste."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_SETUP_SQL)
        yield url


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """ConfiguracaoDeExtracao com percentual=100 — amostra determinística nos testes."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=100))

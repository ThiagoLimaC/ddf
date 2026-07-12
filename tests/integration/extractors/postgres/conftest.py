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

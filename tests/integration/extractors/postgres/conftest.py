"""Fixtures de integração de ExtratorPostgres — Postgres real via testcontainers."""

from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
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

    -- Índices UNIQUE "especiais" (issue #89, achados da banca de revisão
    -- contra Postgres 16 real): nenhum dos 3 deve virar RestricaoUnica nem
    -- marcar coluna como unica=True — cada um seria uma classificação
    -- estruturalmente falsa sem os predicados indexprs/indnkeyatts/indpred.
    CREATE TABLE restricoes.indices_especiais (
        id SERIAL PRIMARY KEY,
        col_a INTEGER NOT NULL,
        col_b VARCHAR(50) NOT NULL,
        col_c INTEGER NOT NULL,
        deletado BOOLEAN NOT NULL DEFAULT false
    );

    -- Índice de expressão: UNIQUE(col_a, lower(col_b)) — sem
    -- indexprs IS NULL, o JOIN de attnum falharia pra entrada de
    -- expressão, sobrando só col_a no grupo e marcando-a unica=True à toa.
    CREATE UNIQUE INDEX idx_expressao
        ON restricoes.indices_especiais (col_a, lower(col_b));

    -- Índice covering: só col_c é chave; col_a é coluna INCLUDE, não
    -- participa da unicidade. Sem k.ord <= indnkeyatts, indkey traria as
    -- duas e formaria uma RestricaoUnica(col_c, col_a) inexistente.
    CREATE UNIQUE INDEX idx_covering
        ON restricoes.indices_especiais (col_c) INCLUDE (col_a);

    -- Índice parcial (soft-delete): só garante unicidade condicional
    -- (deletado = false), não da tabela inteira. Sem indpred IS NULL,
    -- viraria RestricaoUnica(col_a, col_b) mesmo sem essa garantia.
    CREATE UNIQUE INDEX idx_parcial
        ON restricoes.indices_especiais (col_a, col_b) WHERE deletado = false;

    INSERT INTO restricoes.indices_especiais (col_a, col_b, col_c)
        VALUES (1, 'x', 100);

    ANALYZE restricoes.indices_especiais;

    -- Colunas ARRAY (issue #56, Fase 1): tags/numeros cobrem elemento
    -- reconhecido (TEXT/INTEGER), array vazio (linha 2) e array nulo
    -- (linha 3) — reproduz o crash de InvalidOperationError encontrado na
    -- auditoria (.min()/.max() sobre dtype pl.List).
    CREATE SCHEMA arrays;

    CREATE TABLE arrays.colunas_array (
        id SERIAL PRIMARY KEY,
        tags TEXT[],
        numeros INTEGER[]
    );

    INSERT INTO arrays.colunas_array (tags, numeros) VALUES
        (ARRAY['a', 'b'], ARRAY[1, 2, 3]),
        (ARRAY['c'], ARRAY[]::INTEGER[]),
        (NULL, NULL);

    ANALYZE arrays.colunas_array;

    -- Reproduz o achado da issue #76 (revisão da banca): TRUNCATE zera
    -- n_live_tup mas deixa reltuples com o valor antigo indefinidamente
    -- (sem gatilho de autovacuum depois de TRUNCATE) — prova que a query
    -- de total_linhas usa pg_relation_size(oid) = 0 como sinal físico,
    -- não só estatística de catálogo.
    CREATE SCHEMA truncamento;

    CREATE TABLE truncamento.tabela_truncada (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(50) NOT NULL
    );

    INSERT INTO truncamento.tabela_truncada (nome)
        SELECT 'linha_' || gs FROM generate_series(1, 100) gs;

    ANALYZE truncamento.tabela_truncada;

    TRUNCATE truncamento.tabela_truncada;

    -- Tabela com massa suficiente pra amostragem percentual/seed fazerem
    -- sentido estatisticamente (issue #76) — as tabelas de 3 linhas acima
    -- são pequenas demais pra provar reprodutibilidade com confiança.
    CREATE SCHEMA reprodutibilidade;

    CREATE TABLE reprodutibilidade.itens (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(50) NOT NULL
    );

    INSERT INTO reprodutibilidade.itens (nome)
        SELECT 'item_' || gs FROM generate_series(1, 500) gs;

    ANALYZE reprodutibilidade.itens;

    -- Colisão de nome de constraint FK entre tabelas do mesmo schema
    -- (achado da banca de revisão pós-implementação da #95, validado
    -- primeiro manualmente contra Postgres 16 real): constraint_name de FK
    -- não é único por schema, só por tabela (pg_constraint é unique em
    -- (conrelid, conname)) — duas tabelas podem ter FK nomeada igual
    -- apontando para alvos diferentes. Prova que a query via pg_catalog
    -- (conrelid/confrelid, por OID) resolve cada uma para o alvo certo, ao
    -- contrário da query anterior (information_schema, por nome), que
    -- devolvia o alvo errado/duplicado nesse cenário.
    CREATE SCHEMA colisao_fk;

    CREATE TABLE colisao_fk.alvo_a (id INTEGER PRIMARY KEY);
    CREATE TABLE colisao_fk.alvo_b (id INTEGER PRIMARY KEY);

    CREATE TABLE colisao_fk.filho_a (
        id SERIAL PRIMARY KEY,
        alvo_id INTEGER NOT NULL,
        CONSTRAINT fk_pai FOREIGN KEY (alvo_id) REFERENCES colisao_fk.alvo_a(id)
    );

    CREATE TABLE colisao_fk.filho_b (
        id SERIAL PRIMARY KEY,
        alvo_id INTEGER NOT NULL,
        CONSTRAINT fk_pai FOREIGN KEY (alvo_id) REFERENCES colisao_fk.alvo_b(id)
    );

    INSERT INTO colisao_fk.alvo_a (id) VALUES (1);
    INSERT INTO colisao_fk.alvo_b (id) VALUES (1);
    INSERT INTO colisao_fk.filho_a (alvo_id) VALUES (1);
    INSERT INTO colisao_fk.filho_b (alvo_id) VALUES (1);

    ANALYZE colisao_fk.alvo_a;
    ANALYZE colisao_fk.alvo_b;
    ANALYZE colisao_fk.filho_a;
    ANALYZE colisao_fk.filho_b;
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

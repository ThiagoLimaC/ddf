"""Fixtures de integração de ExtratorPostgres — Postgres real via testcontainers."""

from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
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

    -- FK polimórfica (issue #105): coluna com 2 constraints FK distintas de
    -- coluna única apontando pra tabelas diferentes — achado real contra um
    -- MariaDB gerenciado com 843 tabelas (issue #104), replicado aqui contra
    -- Postgres real pra provar que a mudança é agnóstica de fonte.
    CREATE SCHEMA polimorfismo;

    CREATE TABLE polimorfismo.clientes (id INTEGER PRIMARY KEY);
    CREATE TABLE polimorfismo.fornecedores (id INTEGER PRIMARY KEY);

    CREATE TABLE polimorfismo.movimentos (
        id SERIAL PRIMARY KEY,
        entidade_id INTEGER NOT NULL,
        CONSTRAINT fk_movimentos_clientes
            FOREIGN KEY (entidade_id) REFERENCES polimorfismo.clientes(id),
        CONSTRAINT fk_movimentos_fornecedores
            FOREIGN KEY (entidade_id) REFERENCES polimorfismo.fornecedores(id)
    );

    INSERT INTO polimorfismo.clientes (id) VALUES (1);
    INSERT INTO polimorfismo.fornecedores (id) VALUES (1);
    INSERT INTO polimorfismo.movimentos (entidade_id) VALUES (1);

    ANALYZE polimorfismo.clientes;
    ANALYZE polimorfismo.fornecedores;
    ANALYZE polimorfismo.movimentos;

    -- Coluna TEXT altamente compressível: pg_stats.avg_width reflete o
    -- tamanho armazenado após compressão TOAST, não o tamanho real que o
    -- driver recebe ao ler a linha — repeat('a', 50000) comprime pra uma
    -- fração do tamanho real, prova que a sonda física (TABLESAMPLE +
    -- octet_length) mede o valor real, não o comprimido.
    CREATE SCHEMA largura_real;

    CREATE TABLE largura_real.tabela_larga (
        id SERIAL PRIMARY KEY,
        conteudo TEXT NOT NULL
    );

    INSERT INTO largura_real.tabela_larga (conteudo)
        SELECT repeat('a', 50000) FROM generate_series(1, 50);

    ANALYZE largura_real.tabela_larga;

    -- Coluna ARRAY também é sujeita a compressão TOAST, mas seu
    -- udt_name (`_text`) não bate com nenhum nome de tipo escalar —
    -- prova que a detecção via `pg_attribute.attstorage` cobre isso, ao
    -- contrário de uma lista fixa de nomes de tipo.
    CREATE TABLE largura_real.tabela_com_array (
        id SERIAL PRIMARY KEY,
        tags TEXT[] NOT NULL
    );

    INSERT INTO largura_real.tabela_com_array (tags)
        SELECT ARRAY(SELECT repeat('x', 100) FROM generate_series(1, 500))
        FROM generate_series(1, 20);

    ANALYZE largura_real.tabela_com_array;

    -- Coluna com STORAGE EXTERNAL (fora de linha, sem compressão) —
    -- avg_width reflete só o ponteiro TOAST (poucos bytes), subestimativa
    -- ainda maior que EXTENDED/MAIN, e continua sujeita à mesma sonda.
    CREATE TABLE largura_real.tabela_com_external (
        id SERIAL PRIMARY KEY,
        conteudo TEXT NOT NULL
    );
    ALTER TABLE largura_real.tabela_com_external
        ALTER COLUMN conteudo SET STORAGE EXTERNAL;

    INSERT INTO largura_real.tabela_com_external (conteudo)
        SELECT repeat('y', 50000) FROM generate_series(1, 20);

    ANALYZE largura_real.tabela_com_external;

    -- Tabela particionada declarativamente (issue #141): mãe + 2 partições
    -- reais por RANGE. reltuples da mãe fica -1 (nunca analisada por
    -- autovacuum, que só cobre relkind='r') mesmo com as filhas com dado
    -- real e analisadas — prova que a agregação via pg_inherits é
    -- necessária, não só um efeito de esquecer ANALYZE na mãe.
    CREATE SCHEMA particionamento;

    CREATE TABLE particionamento.pedidos (
        id SERIAL,
        ano INTEGER NOT NULL,
        valor NUMERIC(10, 2) NOT NULL
    ) PARTITION BY RANGE (ano);

    CREATE TABLE particionamento.pedidos_2024
        PARTITION OF particionamento.pedidos
        FOR VALUES FROM (2024) TO (2025);

    CREATE TABLE particionamento.pedidos_2025
        PARTITION OF particionamento.pedidos
        FOR VALUES FROM (2025) TO (2026);

    INSERT INTO particionamento.pedidos (ano, valor)
        SELECT 2024, 10.00 FROM generate_series(1, 30);
    INSERT INTO particionamento.pedidos (ano, valor)
        SELECT 2025, 20.00 FROM generate_series(1, 20);

    ANALYZE particionamento.pedidos_2024;
    ANALYZE particionamento.pedidos_2025;

    -- Herança clássica (não particionamento declarativo) convivendo no
    -- mesmo schema: prova que o filtro relkind='p' no pai (em
    -- _LISTAR_TABELAS_SQL/_FILHOS_DE_PARTICAO_SCHEMA_SQL) não confunde
    -- INHERITS comum com partição — veiculo é tabela real e independente,
    -- não deve ser excluída da listagem nem entrar na agregação de
    -- particionamento.pedidos.
    CREATE TABLE particionamento.veiculo (
        id SERIAL PRIMARY KEY,
        placa VARCHAR(10) NOT NULL
    );

    CREATE TABLE particionamento.carro (
        km_rodado INTEGER NOT NULL
    ) INHERITS (particionamento.veiculo);

    INSERT INTO particionamento.veiculo (placa) VALUES ('AAA0000');
    INSERT INTO particionamento.carro (placa, km_rodado) VALUES ('BBB0000', 1000);

    ANALYZE particionamento.veiculo;
    ANALYZE particionamento.carro;

    -- Particionamento de 2 níveis (issue #141, achado da banca pós-
    -- implementação): eventos -> eventos_2023 (ela mesma particionada) ->
    -- eventos_2023_q1/q2 (folhas físicas). pg_inherits devolve as linhas
    -- na ordem pai-antes-do-filho — prova que a agregação de total_linhas
    -- da raiz não pode depender de um único passe bottom-up nessa ordem.
    CREATE SCHEMA particionamento_multinivel;

    CREATE TABLE particionamento_multinivel.eventos (
        id SERIAL,
        ano INTEGER NOT NULL,
        trimestre INTEGER NOT NULL,
        tipo VARCHAR(20) NOT NULL
    ) PARTITION BY RANGE (ano);

    CREATE TABLE particionamento_multinivel.eventos_2023
        PARTITION OF particionamento_multinivel.eventos
        FOR VALUES FROM (2023) TO (2024)
        PARTITION BY RANGE (trimestre);

    CREATE TABLE particionamento_multinivel.eventos_2023_q1
        PARTITION OF particionamento_multinivel.eventos_2023
        FOR VALUES FROM (1) TO (2);

    CREATE TABLE particionamento_multinivel.eventos_2023_q2
        PARTITION OF particionamento_multinivel.eventos_2023
        FOR VALUES FROM (2) TO (3);

    INSERT INTO particionamento_multinivel.eventos (ano, trimestre, tipo)
        SELECT 2023, 1, 'compra' FROM generate_series(1, 15);
    INSERT INTO particionamento_multinivel.eventos (ano, trimestre, tipo)
        SELECT 2023, 2, 'devolucao' FROM generate_series(1, 10);

    ANALYZE particionamento_multinivel.eventos_2023_q1;
    ANALYZE particionamento_multinivel.eventos_2023_q2;
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

"""Queries SQL cruas usadas por ExtratorPostgres, separadas do código que as lê."""

_LISTAR_ESCOPOS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
      AND schema_name NOT LIKE 'pg_temp_%'
      AND schema_name NOT LIKE 'pg_toast_temp_%'
    ORDER BY schema_name
"""

_LISTAR_TABELAS_SQL = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COLUNAS_SCHEMA_SQL = """
    SELECT table_name, column_name, udt_name, character_maximum_length,
           numeric_precision, numeric_scale, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s
    ORDER BY table_name, ordinal_position
"""

_CHAVES_PRIMARIAS_SCHEMA_SQL = """
    SELECT tc.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
        AND tc.table_schema = %s
"""

_CHAVES_ESTRANGEIRAS_SCHEMA_SQL = """
    SELECT tc.table_name AS tabela_de_origem, kcu.column_name,
           ccu.table_schema, ccu.table_name, ccu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
        AND tc.constraint_schema = rc.constraint_schema
    JOIN information_schema.key_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
        AND rc.unique_constraint_schema = ccu.constraint_schema
        AND kcu.position_in_unique_constraint = ccu.ordinal_position
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s
"""

# relkind IN ('r', 'p') — bug pré-existente encontrado no desenho da issue
# #66 (não introduzido aqui): sem o filtro, information_schema.tables já
# classifica tabela particionada (relkind='p') como BASE TABLE normalmente,
# mas reltuples do pai particionado só agrega os filhos a partir do PG14 —
# podia ficar em 0 mesmo com dado real nas partições em versões anteriores.
# O join por nome contra pg_namespace já blindava contra pegar a relação
# errada (Postgres não permite colisão de nome entre tabela/view/sequence no
# mesmo schema); o filtro é defesa explícita do tipo de relação, não
# correção de uma colisão observada.
#
# n_live_tup: contador incremental, mais atual que reltuples entre
# ANALYZEs, sem custo adicional. NULLIF(s.n_live_tup, 0) trata "sem
# estatística reportada ainda" como ausência, não zero real.
#
# CASE cobre o que reltuples também erra: TRUNCATE zera n_live_tup mas
# deixa reltuples com o valor antigo indefinidamente (sem gatilho de
# autovacuum depois de TRUNCATE). pg_relation_size(oid) = 0 é sinal físico
# (arquivo vazio) — relkind <> 'p' exclui tabela-mãe particionada, que
# sempre tem tamanho 0 por não ter storage próprio. NULLIF(reltuples, -1)
# trata "nunca analisada" como ausência, não zero.
#
# Limitação aceita: DELETE em massa sem TRUNCATE, antes do autovacuum
# truncar páginas vazias, ainda pode reportar total desatualizado — sem
# sinal de catálogo barato pra esse caso (issue #76).
_TOTAL_LINHAS_SCHEMA_SQL = """
    SELECT c.relname,
           COALESCE(
               NULLIF(s.n_live_tup, 0),
               CASE
                   WHEN c.relkind <> 'p' AND pg_relation_size(c.oid) = 0
                       THEN 0
                   ELSE NULLIF(c.reltuples, -1)
               END,
               0
           ) AS linhas_estimadas
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
    WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
"""

# Via pg_index (catálogo), não information_schema.table_constraints como
# PK/FK acima: todo UNIQUE constraint no Postgres é backed por um índice em
# pg_index, então esta única query cobre tanto constraint UNIQUE nomeada
# quanto CREATE UNIQUE INDEX solto (sem ADD CONSTRAINT) — o segundo caso não
# aparece em information_schema.table_constraints de jeito nenhum.
# NOT i.indisprimary exclui PK sem lógica extra: o índice de suporte de uma
# PK nunca aparece como uma segunda entrada indisunique "solta".
_COLUNAS_UNICAS_SCHEMA_SQL = """
    SELECT t.relname, a.attname
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
    WHERE i.indisunique AND NOT i.indisprimary
        AND array_length(i.indkey, 1) = 1
        AND n.nspname = %s
"""

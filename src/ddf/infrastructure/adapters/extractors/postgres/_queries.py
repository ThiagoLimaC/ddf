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

# Via pg_constraint (contype='f'): o JOIN anterior (information_schema, por
# constraint_name + table_schema) colidia entre tabelas do mesmo schema com
# FK de mesmo nome (ex.: convenção `fk_parent` repetida em várias filhas), devolvendo
# a tabela/coluna referenciada errada. `conrelid`/`confrelid` (OID) evitam
# depender de nome. `unnest(conkey, confkey) WITH ORDINALITY` desempacota os
# dois arrays em paralelo — cada posição `ord` pareia a coluna local
# (`conkey[ord]`) com a coluna referenciada correspondente (`confkey[ord]`),
# cobrindo FK single-column e composta na mesma passada (issue #95).
# ORDER BY estabiliza a ordem das colunas dentro de uma constraint composta
# entre execuções (mesmo achado da banca da #89 pra restrições únicas — sem
# ordem garantida, o hash estrutural oscilaria sem mudança real de schema).
_CHAVES_ESTRANGEIRAS_SCHEMA_SQL = """
    SELECT t.relname, a_local.attname,
           rn.nspname, rt.relname, a_ref.attname,
           c.conname
    FROM pg_catalog.pg_constraint c
    JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_catalog.pg_class rt ON rt.oid = c.confrelid
    JOIN pg_catalog.pg_namespace rn ON rn.oid = rt.relnamespace
    JOIN LATERAL unnest(c.conkey, c.confkey)
        WITH ORDINALITY AS k(local_attnum, ref_attnum, ord) ON true
    JOIN pg_catalog.pg_attribute a_local
        ON a_local.attrelid = t.oid AND a_local.attnum = k.local_attnum
    JOIN pg_catalog.pg_attribute a_ref
        ON a_ref.attrelid = rt.oid AND a_ref.attnum = k.ref_attnum
    WHERE c.contype = 'f'
        AND n.nspname = %s
    ORDER BY t.relname, c.conname, k.ord
"""

# relkind IN ('r', 'p'): sem isso, tabela particionada (relkind='p') tinha
# reltuples zerado em versões pré-PG14, mesmo com dado real nas partições
# (issue #66).
#
# n_live_tup: contador incremental, mais atual que reltuples entre
# ANALYZEs. NULLIF(s.n_live_tup, 0) trata "sem estatística ainda" como
# ausência, não zero real.
#
# CASE cobre o que reltuples também erra: TRUNCATE zera n_live_tup mas
# deixa reltuples desatualizado indefinidamente. pg_relation_size(oid) = 0
# é sinal físico de tabela vazia; relkind <> 'p' exclui tabela-mãe
# particionada (sempre tamanho 0). NULLIF(reltuples, -1) trata "nunca
# analisada" como ausência.
#
# Limitação aceita: DELETE em massa sem TRUNCATE, antes do autovacuum
# truncar páginas vazias, ainda pode reportar total desatualizado (#76).
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

# Via pg_index, não information_schema.table_constraints: cobre também
# CREATE UNIQUE INDEX solto. NOT i.indisprimary exclui PK. unnest(indkey)
# WITH ORDINALITY desempacota todas as colunas de cada índice (não só a
# 1ª), cobrindo single-column e composto numa passada só, agrupados depois
# em Python por (nome_tabela, indexrelid); k.ord preserva a ordem.
#
# Predicados extra (issue #89, achados da banca contra Postgres 16 real —
# sem eles, cenários abaixo produziriam RestricaoUnica/unica falsos):
#   - indexprs IS NULL: ignora índice com coluna de expressão (o JOIN de
#     attnum falha pra ela, sobrando só as colunas reais no grupo).
#   - k.ord <= indnkeyatts: ignora coluna INCLUDE de índice covering.
#   - indpred IS NULL: ignora índice UNIQUE parcial (ex.: soft-delete) —
#     não é garantia de unicidade da tabela inteira.
#   - indisvalid: ignora índice inválido (ex.: CONCURRENTLY que falhou).
_RESTRICOES_UNICAS_SCHEMA_SQL = """
    SELECT t.relname, i.indexrelid, a.attname
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
    JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = t.oid AND a.attnum = k.attnum
    WHERE i.indisunique AND NOT i.indisprimary
        AND i.indexprs IS NULL
        AND i.indpred IS NULL
        AND i.indisvalid
        AND k.ord <= i.indnkeyatts
        AND n.nspname = %s
    ORDER BY t.relname, i.indexrelid, k.ord
"""

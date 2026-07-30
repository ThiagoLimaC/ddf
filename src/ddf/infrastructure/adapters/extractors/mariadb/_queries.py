"""Queries SQL cruas usadas por ExtratorMariaDB, separadas do código que as lê."""

_LISTAR_ESCOPOS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN
        ('information_schema', 'mysql', 'performance_schema', 'sys')
    ORDER BY schema_name
"""

_LISTAR_TABELAS_SQL = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COLUNAS_SQL = """
    SELECT column_name, data_type, column_type, character_maximum_length,
           numeric_precision, numeric_scale, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
"""

_CHAVES_PRIMARIAS_SQL = """
    SELECT column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s AND constraint_name = 'PRIMARY'
    ORDER BY ordinal_position
"""

# constraint_name/ORDER BY (issue #95): a query já filtrava por tabela,
# mas não expunha constraint_name nem garantia ordem — sem os dois, o
# código Python não tinha como agrupar colunas de uma mesma FK composta de
# forma estável entre execuções (mesmo achado da banca da #89 pro
# agrupamento de UNIQUE composto em _COLUNAS_UNICAS_SQL).
_CHAVES_ESTRANGEIRAS_SQL = """
    SELECT column_name, referenced_table_schema, referenced_table_name,
           referenced_column_name, constraint_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s
      AND referenced_table_name IS NOT NULL
    ORDER BY constraint_name, ordinal_position
"""

_TOTAL_LINHAS_SQL = """
    SELECT table_rows
    FROM information_schema.tables
    WHERE table_schema = %s AND table_name = %s
"""

# AND kcu.table_name = %s nos dois lados do JOIN: nomes de constraint no
# MariaDB são escopados por TABELA, não por schema — duas tabelas do mesmo
# schema podem ter uma UNIQUE KEY com nome idêntico (ex.: "email" gerado por
# UNIQUE(email) em tabelas diferentes). Sem esse filtro, o JOIN por
# constraint_name+table_schema cruza linhas de tabelas diferentes e classifica
# colunas UNIQUE reais como não-únicas por acidente (validado empiricamente
# contra MariaDB 11 real durante a revisão desta issue).
#
# ORDER BY ordinal_position (issue #89): sem isso, a ordem das colunas
# dentro de uma constraint composta não é garantida entre execuções — o
# hash estrutural (SobrescritaDeTabela) dispararia falso positivo de
# "estrutura alterada" sem nenhuma mudança real de schema.
_COLUNAS_UNICAS_SQL = """
    SELECT kcu.constraint_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
        AND tc.table_name = kcu.table_name
    WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s AND tc.table_name = %s
    ORDER BY kcu.constraint_name, kcu.ordinal_position
"""
# `_construir_coluna` só aceita um match de `_extrair_coluna_json_valid`
# se o nome extraído também existir entre as colunas reais desta tabela
# (`linhas_colunas`) — a validação cruzada é o que torna este SELECT sem
# filtro de tabela seguro de usar.
_COLUNAS_JSON_SQL = """
    SELECT cc.check_clause
    FROM information_schema.table_constraints tc
    JOIN information_schema.check_constraints cc
        ON tc.constraint_schema = cc.constraint_schema
        AND tc.constraint_name = cc.constraint_name
    WHERE tc.constraint_type = 'CHECK'
        AND tc.table_schema = %s AND tc.table_name = %s
"""

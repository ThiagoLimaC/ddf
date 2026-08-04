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
    SELECT table_name, column_name, data_type, column_type,
           character_maximum_length, numeric_precision, numeric_scale,
           is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s
    ORDER BY table_name, ordinal_position
"""

_CHAVES_PRIMARIAS_SQL = """
    SELECT table_name, column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND constraint_name = 'PRIMARY'
    ORDER BY table_name, ordinal_position
"""

# constraint_name/ORDER BY: sem os dois, o código Python não tem como
# agrupar colunas de uma mesma FK composta de forma estável entre execuções
# (mesmo raciocínio do agrupamento de UNIQUE composto em
# _COLUNAS_UNICAS_SQL).
_CHAVES_ESTRANGEIRAS_SQL = """
    SELECT table_name, column_name, referenced_table_schema,
           referenced_table_name, referenced_column_name, constraint_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s
      AND referenced_table_name IS NOT NULL
    ORDER BY table_name, constraint_name, ordinal_position
"""

# avg_row_length já vem de graça na mesma linha de catálogo de table_rows —
# zero query nova pra estimar largura média de linha. NULL/0 (tabela nunca
# analisada) é tratado por quem lê, com um fallback conservador
# (LARGURA_MEDIA_PADRAO_BYTES), não uma exceção.
_TOTAL_LINHAS_SQL = """
    SELECT table_name, table_rows, avg_row_length
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
"""

# AND kcu.table_name = tc.table_name no JOIN (não só no WHERE): nomes de
# constraint no MariaDB são escopados por TABELA, não pelo escopo inteiro —
# duas tabelas do mesmo escopo podem ter uma UNIQUE KEY com nome idêntico
# (ex.: "email" gerado por UNIQUE(email) em tabelas diferentes). Sem esse
# cruzamento no JOIN, linhas de tabelas diferentes se misturariam ao
# consultar o escopo inteiro de uma vez. O agrupamento em Python precisa
# usar a chave composta (table_name, constraint_name), não só
# constraint_name — ver _particionar_colunas_unicas.
#
# ORDER BY ordinal_position: sem isso, a ordem das colunas dentro de uma
# constraint composta não é garantida entre execuções — o hash estrutural
# (SobrescritaDeTabela) dispararia falso positivo de "estrutura alterada"
# sem nenhuma mudança real de schema.
_COLUNAS_UNICAS_SQL = """
    SELECT tc.table_name, kcu.constraint_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
        AND tc.table_name = kcu.table_name
    WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s
    ORDER BY tc.table_name, kcu.constraint_name, kcu.ordinal_position
"""

# information_schema.check_constraints já traz table_name diretamente —
# atribui cada CHECK à tabela correta sem precisar de JOIN com
# table_constraints, mesmo quando duas tabelas do mesmo escopo usam
# constraint_name idêntico. `_colunas_json_de_check_clauses` cruza o
# resultado contra as colunas reais de cada tabela como defesa adicional
# contra CHECK_CLAUSE fora do padrão esperado.
_COLUNAS_JSON_SQL = """
    SELECT table_name, check_clause
    FROM information_schema.check_constraints
    WHERE constraint_schema = %s
"""

LARGURA_MEDIA_PADRAO_BYTES = 200
"""Fallback conservador (bytes/linha) para `avg_row_length` NULL/0.

Tabela nunca analisada não tem essa estatística populada — ausência não
impede o cálculo de tamanho de lote do streaming, só faz a estimativa cair
nesse valor conservador.
"""

{% macro mariadb__validate_format(column_expression, pattern) %}
{#
    REGEXP é case-insensitive por padrão quando a coluna usa collation `_ci`
    (o caso comum). Colunas com collation `_cs`/`_bin` explícita fogem desse
    padrão e podem divergir do que a amostra validou (mesmo risco de
    case-sensitivity do lado Postgres, resolvido lá via `~*`) — limitação
    conhecida, documentada no README do projeto dbt gerado.
#}
    {{ column_expression }} REGEXP '{{ pattern }}'
{% endmacro %}

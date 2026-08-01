{% macro mariadb__validate_format(column_expression, pattern) %}
{# REGEXP é case-insensitive por padrão sob collation `_ci` (ver docs/low_level_design.md para a limitação com `_cs`/`_bin`). #}
    {{ column_expression }} REGEXP '{{ pattern }}'
{% endmacro %}

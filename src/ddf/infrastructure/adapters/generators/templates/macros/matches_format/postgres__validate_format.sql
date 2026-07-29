{% macro postgres__validate_format(column_expression, pattern) %}
{#
    `~*` (não `~`) — Postgres é case-sensitive por padrão em `~`, e o regex
    fonte de email em detector_de_formato.py usa re.IGNORECASE. Sem `~*`, este
    teste divergiria do que a amostra realmente validou para gerar a sugestão.
#}
    {{ column_expression }} ~* '{{ pattern }}'
{% endmacro %}

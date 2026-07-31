{% macro postgres__validate_format(column_expression, pattern) %}
{# ~* (case-insensitive) para paridade com re.IGNORECASE em detector_de_formato.py. #}
    {{ column_expression }} ~* '{{ pattern }}'
{% endmacro %}

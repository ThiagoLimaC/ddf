{% macro postgres__cast_type(column_expression, tipo_canonico, precisao_fracionaria=none) %}
{# Postgres aceita o literal canônico sem tradução — passthrough. precisao_fracionaria é ignorada: CAST sem precisão explícita já preserva microssegundos por padrão neste motor (diferente do MariaDB, que trunca em silêncio sem o sufixo (n)). #}
    CAST({{ column_expression }} AS {{ tipo_canonico }})
{% endmacro %}

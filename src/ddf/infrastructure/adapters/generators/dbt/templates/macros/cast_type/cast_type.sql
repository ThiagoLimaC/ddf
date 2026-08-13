{% macro cast_type(column_expression, tipo_canonico, precisao_fracionaria=none) %}
{# Dispatch por adapter da tradução de tipo em CAST. `tipo_canonico` é o literal ANSI que `_tipo_sql` já produz pra qualquer motor de origem (Postgres aceita sem tradução; outros adapters traduzem). `precisao_fracionaria` (0-6) só se aplica a TIMESTAMP/TIME — cada <adapter>__cast_type.sql decide se repassa, ignora ou traduz. #}
{{ adapter.dispatch('cast_type', 'ddf_staging')(column_expression, tipo_canonico, precisao_fracionaria) }}
{% endmacro %}

{% macro default__cast_type(column_expression, tipo_canonico, precisao_fracionaria=none) %}
    {{ exceptions.raise_compiler_error(
        "cast_type: adapter '" ~ target.type ~ "' não tem implementação de "
        "cast_type. Implementações disponíveis nesta versão: postgres, "
        "mariadb (ver macros/cast_type/*__cast_type.sql). Para dar suporte "
        "a uma engine nova, adicione macros/cast_type/<adapter>__cast_type.sql "
        "implementando "
        "<adapter>__cast_type(column_expression, tipo_canonico, precisao_fracionaria=none)."
    ) }}
{% endmacro %}

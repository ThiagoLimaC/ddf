{% test matches_format(model, column_name, format) %}
{# Valida a coluna contra o regex de `format` (patterns = cópia de detector_de_formato.py). Validação real por engine em <adapter>__validate_format.sql. #}

{% set patterns = {
    'email': '^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$',
    'cpf': '^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$',
    'cnpj': '^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$',
    'phone': '^(\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}$',
    'cep': '^\d{5}-?\d{3}$'
} %}

with validation as (

    select {{ column_name }} as value_to_check
    from {{ model }}
    where {{ column_name }} is not null

),

validation_errors as (

    select value_to_check
    from validation
    where not (
        {{ adapter.dispatch('validate_format', 'ddf_staging')('value_to_check', patterns[format]) }}
    )

)

select *
from validation_errors

{% endtest %}

{% macro default__validate_format(column_expression, pattern) %}
    {{ exceptions.raise_compiler_error(
        "matches_format: adapter '" ~ target.type ~ "' não tem implementação de "
        "validate_format. Implementações disponíveis nesta versão: postgres, "
        "mariadb (ver macros/matches_format/*__validate_format.sql). Para dar "
        "suporte a uma engine nova, adicione "
        "macros/matches_format/<adapter>__validate_format.sql implementando "
        "<adapter>__validate_format(column_expression, pattern)."
    ) }}
{% endmacro %}

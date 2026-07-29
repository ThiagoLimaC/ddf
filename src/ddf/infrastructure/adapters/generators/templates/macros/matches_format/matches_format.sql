{% test matches_format(model, column_name, format) %}
{#
    Teste genérico dbt: valida que uma coluna casa com um dos formatos
    conhecidos (email/cpf/cnpj/phone/cep). `format` é o valor de
    `formato_detectado` que o AnalisadorDeMetricasDeColuna do ddf já calculou
    sobre a amostra — os patterns abaixo são cópia literal dos regex fonte em
    detector_de_formato.py, não uma reinvenção.

    A validação real (`{{ column_expression }} <op> <pattern>`) é delegada por
    engine via adapter.dispatch — cada warehouse de destino tem sintaxe de
    regex própria. Ver postgres__validate_format.sql/mariadb__validate_format.sql
    neste mesmo diretório para as implementações suportadas nesta v1; engines
    fora dessas duas caem no default__validate_format abaixo, que falha
    explicitamente em vez de silenciosamente.
#}

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

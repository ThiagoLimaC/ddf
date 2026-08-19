{% test composite_relationships(model, column_names, to, field_names) %}
{# Integridade referencial de FK composta: testa que a combinação de column_names existe em to.field_names — nem dbt-core nem dbt_utils têm equivalente pronto pra relationships multi-coluna. Linha com qualquer coluna local NULL é excluída (MATCH SIMPLE, mesma semântica do relationships nativo). Comparação via NOT EXISTS/igualdade por coluna — SQL ANSI puro, sem depender de sintaxe de tupla/ROW específica de engine. #}

with child as (

    select *
    from {{ model }}
    where
    {% for column in column_names %}
        {{ column }} is not null
        {%- if not loop.last %} and {% endif %}
    {% endfor %}

),

validation_errors as (

    select child.*
    from child
    where not exists (
        select 1
        from {{ to }} as parent
        where
        {% for column in column_names %}
            child.{{ column }} = parent.{{ field_names[loop.index0] }}
            {%- if not loop.last %} and {% endif %}
        {% endfor %}
    )

)

select *
from validation_errors

{% endtest %}

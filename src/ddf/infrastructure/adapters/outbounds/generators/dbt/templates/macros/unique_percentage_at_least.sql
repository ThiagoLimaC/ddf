{% test unique_percentage_at_least(model, column_name, at_least) %}
{# Falha (warn) quando a fração de valores distintos entre os não-nulos fica abaixo de at_least. #}

with aggregated as (

    select
        count(distinct {{ column_name }}) as distinct_count,
        count({{ column_name }}) as non_null_count
    from {{ model }}
    where {{ column_name }} is not null

)

select *
from aggregated
where non_null_count > 0
  and (distinct_count * 1.0 / non_null_count) < {{ at_least }}

{% endtest %}

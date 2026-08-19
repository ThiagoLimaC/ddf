{% macro mariadb__cast_type(column_expression, tipo_canonico, precisao_fracionaria=none) %}
{# CAST() do MariaDB aceita só um allow-list fixo de tipos-alvo, distinto dos nomes de tipo de coluna — traduz o literal canônico pro equivalente aceito. DATETIME/TIME sem sufixo (n) truncam fração de segundo em silêncio — por isso o grupo temporal sempre recebe precisao_fracionaria explícita (0-6, capturada na extração), nunca hardcoded. TIME WITH TIME ZONE não tem equivalente no motor, cai em TIME (perde o offset). #}
{% set mapa_simples = {
    'BIGINT': 'SIGNED',
    'TEXT': 'CHAR',
    'BOOLEAN': 'UNSIGNED',
    'JSON': 'CHAR',
    'DOUBLE PRECISION': 'DOUBLE',
    'REAL': 'FLOAT'
} %}
{% set mapa_temporal = {
    'TIMESTAMP': 'DATETIME',
    'TIMESTAMP WITH TIME ZONE': 'DATETIME',
    'TIME': 'TIME',
    'TIME WITH TIME ZONE': 'TIME'
} %}
{% if tipo_canonico == 'NUMERIC' %}
    {{ exceptions.raise_compiler_error(
        "mariadb__cast_type: coluna com NUMERIC sem precisão/escala "
        "declarada — CAST(x AS DECIMAL) sem parâmetros trunca/clipa em "
        "silêncio no MariaDB (vira DECIMAL(10,0) implícito), sem erro "
        "visível. Ajuste a origem pra declarar precisão/escala explícitas, "
        "ou use um override pra fixar o tipo desta coluna."
    ) }}
{% elif tipo_canonico in mapa_simples %}
    CAST({{ column_expression }} AS {{ mapa_simples[tipo_canonico] }})
{% elif tipo_canonico in mapa_temporal %}
    {% set sufixo = '(' ~ precisao_fracionaria ~ ')' if precisao_fracionaria is not none else '' %}
    CAST({{ column_expression }} AS {{ mapa_temporal[tipo_canonico] }}{{ sufixo }})
{% else %}
    {{ exceptions.raise_compiler_error(
        "mariadb__cast_type: tipo '" ~ tipo_canonico ~ "' sem tradução "
        "conhecida pro CAST do MariaDB — adicione uma entrada em `mapa_simples` "
        "ou `mapa_temporal` neste arquivo."
    ) }}
{% endif %}
{% endmacro %}

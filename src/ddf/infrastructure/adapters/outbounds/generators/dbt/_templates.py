"""Carregamento de templates Jinja2 e macros dbt estáticos usados pelo GeradorDbt.

Módulo de dado/IO puro — sem lógica de decisão sobre quando cada template ou
macro é usado (isso vive em `gerador_dbt.py`/`_dbt_testes.py`, que decidem
"precisa" antes de escrever). Macros dbt (`{% test %}`/`{% macro %}`) são
lidos como texto puro, não passam pelo `_ambiente` Jinja2 abaixo — essas tags
só o dbt-core (em runtime do dbt, no ambiente do usuário) sabe interpretar; o
`Environment` deste projeto não tem essa extensão e falharia ao parsear.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_ambiente = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 — saída é SQL/Markdown, não HTML
)
_TEMPLATE_SQL = _ambiente.get_template("stg_tabela.sql.jinja2")
_TEMPLATE_README = _ambiente.get_template("readme.md.jinja2")

_ARQUIVOS_MATCHES_FORMAT = (
    "matches_format.sql",
    "postgres__validate_format.sql",
    "mariadb__validate_format.sql",
)
_CONTEUDO_MATCHES_FORMAT: dict[str, str] = {
    nome: (_TEMPLATES_DIR / "macros" / "matches_format" / nome).read_text()
    for nome in _ARQUIVOS_MATCHES_FORMAT
}
_ARQUIVOS_CAST_TYPE = (
    "cast_type.sql",
    "postgres__cast_type.sql",
    "mariadb__cast_type.sql",
)
_CONTEUDO_CAST_TYPE: dict[str, str] = {
    nome: (_TEMPLATES_DIR / "macros" / "cast_type" / nome).read_text()
    for nome in _ARQUIVOS_CAST_TYPE
}
_CONTEUDO_UNIQUE_PERCENTAGE_AT_LEAST = (
    _TEMPLATES_DIR / "macros" / "unique_percentage_at_least.sql"
).read_text()
_CONTEUDO_COMPOSITE_RELATIONSHIPS = (
    _TEMPLATES_DIR / "macros" / "composite_relationships.sql"
).read_text()

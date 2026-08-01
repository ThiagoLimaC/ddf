"""Ambiente Jinja2 do GeradorMarkdown, com os filtros de `_filtros.py` registrados."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ddf.infrastructure.adapters.generators.markdown._filtros import (
    _escapar_celula,
    _formatar_completude,
    _formatar_restricoes_fk_compostas,
    _formatar_restricoes_unicas,
    _formatar_tipo,
    _linha_qualidade,
    _marcadores_de_restricao,
    _secoes_valores_frequentes,
)

_ambiente = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 — saída é Markdown, não HTML; escapamos "|" à mão
)
_ambiente.filters["escapar"] = _escapar_celula
_ambiente.filters["formatar_tipo"] = _formatar_tipo
_ambiente.filters["marcadores_de_restricao"] = _marcadores_de_restricao
_ambiente.filters["formatar_restricoes_unicas"] = _formatar_restricoes_unicas
_ambiente.filters["formatar_restricoes_fk_compostas"] = (
    _formatar_restricoes_fk_compostas
)
_ambiente.filters["completude"] = _formatar_completude
_ambiente.filters["linha_qualidade"] = _linha_qualidade
_ambiente.filters["secoes_valores_frequentes"] = _secoes_valores_frequentes
_TEMPLATE_TABELA = _ambiente.get_template("tabela.md.jinja2")
_TEMPLATE_INDEX = _ambiente.get_template("index.md.jinja2")

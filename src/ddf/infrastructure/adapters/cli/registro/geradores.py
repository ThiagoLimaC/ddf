"""Registro de Geradores disponíveis para o wizard da CLI."""

from ddf.domain.ports.gerador import Gerador
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.generators.gerador_contexto_de_ia import (
    GeradorContextoDeIA,
)
from ddf.infrastructure.adapters.generators.gerador_dbt import GeradorDbt
from ddf.infrastructure.adapters.generators.gerador_markdown import GeradorMarkdown

GERADORES_REGISTRADOS: dict[str, Gerador] = {}


def registrar_gerador(
    nome: str,
    gerador: Gerador,
    registro: dict[str, Gerador] = GERADORES_REGISTRADOS,
) -> None:
    """Registra um novo Gerador no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: identificador do Gerador exibido ao usuário no wizard (etapa
            de escolha de Geradores).
        gerador: instância do Gerador (construtor sem argumentos).
        registro: Dicionário onde o Gerador é registrado. Usa
            GERADORES_REGISTRADOS por padrão.
    """
    registrar_ou_falhar(nome, "Gerador", gerador, registro)


registrar_gerador("Markdown", GeradorMarkdown())
registrar_gerador("Dbt", GeradorDbt())
registrar_gerador("ContextoDeIA", GeradorContextoDeIA())

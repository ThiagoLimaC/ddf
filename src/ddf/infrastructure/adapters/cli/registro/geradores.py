"""Registro de Geradores disponíveis para o wizard da CLI.

Os Geradores nativos (Markdown/Dbt/ContextoDeIA) não se registram aqui por
chamada direta — são descobertos via entry points do grupo "ddf.geradores"
(declarados em `pyproject.toml`), a mesma via de um plugin de terceiro. Ver
`cli/registro/descoberta.py`.
"""

from ddf.domain.ports.gerador import Gerador
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar

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

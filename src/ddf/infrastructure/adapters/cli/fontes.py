"""Registro de fontes de dados disponíveis para o wizard da CLI."""

from ddf.domain.ports.extrator import Extrator

FONTES_REGISTRADAS: dict[str, type[Extrator]] = {}


def registrar_fonte(
    nome: str,
    classe_extrator: type[Extrator],
    registro: dict[str, type[Extrator]] = FONTES_REGISTRADAS,
) -> None:
    """Registra uma nova fonte de dados no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: Identificador da fonte exibido ao usuário no wizard.
        classe_extrator: Classe de Extrator associada à fonte.
        registro: Dicionário onde a fonte é registrada. Usa
            FONTES_REGISTRADAS por padrão.
    """
    if nome in registro:
        raise ValueError(f"Fonte '{nome}' já está registrada.")
    registro[nome] = classe_extrator

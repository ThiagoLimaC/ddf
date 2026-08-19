"""Helper compartilhado pelos registros de extensão do wizard."""

from typing import TypeVar

T = TypeVar("T")


def registrar_ou_falhar(
    nome: str,
    entidade: str,
    valor: T,
    registro: dict[str, T],
    *,
    feminino: bool = False,
) -> None:
    """Registra `valor` sob `nome` em `registro`; levanta ValueError se já existir.

    Args:
        nome: identificador sob o qual `valor` é registrado.
        entidade: nome da entidade registrada, usado na mensagem de erro
            (ex.: "Analisador", "Gerador", "Extrator", "Estratégia").
        valor: valor a registrar.
        registro: dicionário onde `valor` é registrado.
        feminino: usa a forma feminina do particípio ("registrada") na
            mensagem de erro — necessário para "Estratégia".
    """
    if nome in registro:
        participio = "registrada" if feminino else "registrado"
        raise ValueError(f"{entidade} '{nome}' já está {participio}.")
    registro[nome] = valor

"""Tipo compartilhado para avisos não fatais emitidos por um Estagio."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Aviso:
    """Representa um aviso não fatal emitido durante a execução de um Estagio."""

    mensagem: str
    origem: str

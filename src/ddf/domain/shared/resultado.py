"""Tipo compartilhado para representar sucesso ou falha de um Estagio."""

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from ddf.domain.shared.aviso import Aviso

T = TypeVar("T")


@dataclass(frozen=True)
class Sucesso(Generic[T]):
    """Representa o resultado bem-sucedido da execução de um Estagio."""

    valor: T
    avisos: list[Aviso] = field(default_factory=list)


@dataclass(frozen=True)
class Falha:
    """Representa o resultado malsucedido da execução de um Estagio."""

    erro: str
    avisos: list[Aviso] = field(default_factory=list)


Resultado = Sucesso[T] | Falha

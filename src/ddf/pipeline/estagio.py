"""Contrato genérico de um estágio de pipeline."""

from typing import Protocol, TypeVar

from ddf.domain.shared.resultado import Resultado

Entrada = TypeVar("Entrada", contravariant=True)
Saida = TypeVar("Saida")


class Estagio(Protocol[Entrada, Saida]):
    """Transforma uma Entrada em um Resultado[Saida]."""

    def __call__(self, entrada: Entrada) -> Resultado[Saida]:
        """Executa o estágio sobre a entrada recebida."""
        ...

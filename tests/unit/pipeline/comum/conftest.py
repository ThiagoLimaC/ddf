"""Fixtures compartilhadas para testes de pipeline/comum (compor, seguranca)."""

from collections.abc import Callable

import pytest

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso

EstagioInt = Callable[[int], Resultado[int]]
FabricaEstagioSucesso = Callable[[int, "list[Aviso] | None"], EstagioInt]
FabricaEstagioFalha = Callable[[str, "list[Aviso] | None"], EstagioInt]


@pytest.fixture
def fabrica_estagio_sucesso() -> FabricaEstagioSucesso:
    """Fábrica de Estagio[int, int] que sempre soma um valor e emite avisos dados."""

    def _fabrica(incremento: int, avisos: list[Aviso] | None = None) -> EstagioInt:
        def _estagio(entrada: int) -> Resultado[int]:
            return Sucesso(valor=entrada + incremento, avisos=avisos or [])

        return _estagio

    return _fabrica


@pytest.fixture
def fabrica_estagio_falha() -> FabricaEstagioFalha:
    """Fábrica de Estagio[int, int] que sempre retorna Falha."""

    def _fabrica(erro: str, avisos: list[Aviso] | None = None) -> EstagioInt:
        def _estagio(entrada: int) -> Resultado[int]:
            return Falha(erro=erro, avisos=avisos or [])

        return _estagio

    return _fabrica


@pytest.fixture
def estagio_espiao() -> EstagioInt:
    """Estagio[int, int] que registra se foi chamado, para provar short-circuit."""

    def _estagio(entrada: int) -> Resultado[int]:
        _estagio.chamado = True  # type: ignore[attr-defined]
        return Sucesso(valor=entrada)

    _estagio.chamado = False  # type: ignore[attr-defined]
    return _estagio

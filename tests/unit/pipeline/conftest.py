"""Fixtures compartilhadas para testes de pipeline."""

from collections.abc import Callable

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
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


def _tabela_extraida(nome_escopo: str, nome_tabela: str) -> TabelaExtraida:
    """Constrói uma TabelaExtraida mínima (1 coluna) para os testes de pipeline/."""
    return TabelaExtraida(
        nome_tabela=nome_tabela,
        nome_escopo=nome_escopo,
        colunas=[
            ColunaExtraida(
                nome="id",
                tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
                chave_primaria=True,
            )
        ],
        total_linhas=1,
        amostra=pl.DataFrame({"id": [1]}),
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=1
        ),
    )


@pytest.fixture
def fabrica_tabela_extraida() -> Callable[[str, str], TabelaExtraida]:
    """Expõe o builder de TabelaExtraida pros testes montarem fixtures próprias."""
    return _tabela_extraida

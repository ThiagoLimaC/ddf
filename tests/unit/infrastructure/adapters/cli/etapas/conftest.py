"""Fixtures compartilhadas dos testes de cli/etapas/."""

from collections.abc import Callable, Generator
from contextlib import contextmanager

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import ColunaCurada, TabelaCurada
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida


def _tabela_extraida(nome_escopo: str, nome_tabela: str) -> TabelaExtraida:
    """Constrói uma TabelaExtraida mínima (1 coluna) para os testes de etapas/."""
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


def _tabela_curada(tabela: TabelaExtraida) -> TabelaCurada:
    """Constrói uma TabelaCurada a partir de uma TabelaExtraida, sem curadoria real."""
    return TabelaCurada(
        nome_tabela=tabela.nome_tabela,
        nome_escopo=tabela.nome_escopo,
        colunas=[
            ColunaCurada(
                nome=coluna.nome,
                tipo_dado=coluna.tipo_dado,
                chave_primaria=coluna.chave_primaria,
            )
            for coluna in tabela.colunas
        ],
        total_linhas=tabela.total_linhas,
        amostra=tabela.amostra,
        metadados_amostra=tabela.metadados_amostra,
    )


@pytest.fixture
def fabrica_tabela_curada() -> Callable[[TabelaExtraida], TabelaCurada]:
    """Expõe o builder de TabelaCurada pros testes montarem fixtures próprias."""
    return _tabela_curada


@pytest.fixture(autouse=True)
def sem_ampulheta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitui prompts.ampulheta por um no-op — testa lógica, não a animação."""

    @contextmanager
    def _sem_animacao(mensagem: str) -> Generator[None, None, None]:
        yield

    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.ampulheta", _sem_animacao
    )

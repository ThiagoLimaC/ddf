"""Fixtures compartilhadas dos testes de Geradores."""

from collections.abc import Callable

import pytest

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
)
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


@pytest.fixture
def construir_coluna() -> Callable[..., ColunaAnalisada]:
    """Retorna uma factory que monta uma ColunaAnalisada com defaults razoáveis."""

    def _construir(
        nome: str = "coluna",
        tipo_dado: TipoDeDado | None = None,
        chave_primaria: bool = False,
        chave_estrangeira: bool = False,
        referencia: ReferenciaDeColuna | None = None,
        nao_nulavel: bool = False,
        unica: bool = False,
        metricas: list[MetricasBaseColuna] | None = None,
        papel_de_negocio: str | None = None,
    ) -> ColunaAnalisada:
        return ColunaAnalisada(
            nome=nome,
            tipo_dado=tipo_dado or TipoDeDado(categoria=CategoriaDeDado.INTEGER),
            chave_primaria=chave_primaria,
            chave_estrangeira=chave_estrangeira,
            referencia=referencia,
            nao_nulavel=nao_nulavel,
            unica=unica,
            papel_de_negocio=papel_de_negocio,
            metricas=list(metricas) if metricas is not None else [],
        )

    return _construir


@pytest.fixture
def construir_tabela() -> Callable[..., TabelaAnalisada]:
    """Retorna uma factory que monta uma TabelaAnalisada com defaults razoáveis."""

    def _construir(
        colunas: list[ColunaAnalisada],
        nome_tabela: str = "tabela",
        nome_escopo: str = "escopo",
        total_linhas: int = 100,
        tamanho_amostra: int = 100,
        percentual: float | None = None,
        seed: int | None = None,
        papel_de_negocio: str | None = None,
        regras_de_negocio: list[str] | None = None,
        metricas: list[MetricasBaseTabela] | None = None,
        restricoes_unicas: list[RestricaoUnica] | None = None,
    ) -> TabelaAnalisada:
        return TabelaAnalisada(
            nome_tabela=nome_tabela,
            nome_escopo=nome_escopo,
            colunas=colunas,
            total_linhas=total_linhas,
            papel_de_negocio=papel_de_negocio,
            regras_de_negocio=regras_de_negocio or [],
            metadados_amostra=MetadadosDeAmostra(
                estrategia="percentual_de_linhas",
                tamanho_amostra=tamanho_amostra,
                percentual=percentual,
                seed=seed,
            ),
            metricas=list(metricas) if metricas is not None else [],
            restricoes_unicas=restricoes_unicas or [],
        )

    return _construir


@pytest.fixture
def construir_banco() -> Callable[[list[TabelaAnalisada]], BancoAnalisado]:
    """Retorna uma factory que monta um BancoAnalisado a partir de TabelaAnalisada."""

    def _construir(tabelas: list[TabelaAnalisada]) -> BancoAnalisado:
        return BancoAnalisado(tabelas=tabelas)

    return _construir


@pytest.fixture
def metrica_coluna_completa() -> MetricasBaseColuna:
    """Retorna uma MetricasBaseColuna com todos os campos preenchidos."""
    return MetricasBaseColuna(
        percentual_nulo=10.0,
        percentual_unico=80.0,
        valores_frequentes=[("a", 5), ("b", 3)],
        minimo="1",
        maximo="99",
        formato_detectado="email",
    )

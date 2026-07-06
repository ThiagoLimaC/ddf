"""Testes de ColunaExtraida e TabelaExtraida."""

import polars as pl
import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida


# Caminho feliz
def test_cria_coluna_extraida_com_chave_estrangeira(tipo_integer: TipoDeDado) -> None:
    """Caminho feliz: ColunaExtraida guarda referência de chave estrangeira."""
    coluna = ColunaExtraida(
        nome="cliente_id",
        tipo_dado=tipo_integer,
        chave_estrangeira=True,
        tabela_referenciada="clientes",
        coluna_referenciada="id",
    )

    assert coluna.chave_estrangeira is True
    assert coluna.tabela_referenciada == "clientes"
    assert coluna.coluna_referenciada == "id"


def test_cria_tabela_extraida_com_amostra(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Caminho feliz: TabelaExtraida guarda colunas, amostra e metadados."""
    tabela = TabelaExtraida(
        nome_tabela="pedidos",
        nome_schema="public",
        colunas=[
            ColunaExtraida(nome="id", tipo_dado=tipo_integer, chave_primaria=True)
        ],
        total_linhas=10,
        amostra=amostra_df,
        metadados_amostra=metadados_de_amostra,
    )

    assert tabela.nome_tabela == "pedidos"
    assert tabela.amostra.height == 2


# Erro esperado
def test_coluna_extraida_fk_sem_referencia_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: chave_estrangeira=True sem tabela/coluna referenciada."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaExtraida(
            nome="cliente_id", tipo_dado=tipo_integer, chave_estrangeira=True
        )


def test_coluna_extraida_referencia_sem_fk_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: referência preenchida sem chave_estrangeira=True."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaExtraida(
            nome="cliente_id",
            tipo_dado=tipo_integer,
            tabela_referenciada="clientes",
            coluna_referenciada="id",
        )


def test_tabela_extraida_total_linhas_negativo_levanta_validation_error(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Erro esperado: total_linhas negativo é logicamente impossível."""
    with pytest.raises(ValidationError, match="total_linhas"):
        TabelaExtraida(
            nome_tabela="pedidos",
            nome_schema="public",
            colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
            total_linhas=-1,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
        )


def test_tabela_extraida_com_colunas_duplicadas_levanta_validation_error(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Erro esperado: dois nomes de coluna iguais na mesma tabela."""
    with pytest.raises(ValidationError, match="duplicados"):
        TabelaExtraida(
            nome_tabela="pedidos",
            nome_schema="public",
            colunas=[
                ColunaExtraida(nome="id", tipo_dado=tipo_integer),
                ColunaExtraida(nome="id", tipo_dado=tipo_integer),
            ],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
        )


def test_tabela_extraida_sem_amostra_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: amostra é obrigatória — só TabelaCurada admite None."""
    with pytest.raises(ValidationError):
        TabelaExtraida(
            nome_tabela="pedidos",
            nome_schema="public",
            colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
            total_linhas=10,
            amostra=None,
            metadados_amostra=metadados_de_amostra,
        )  # type: ignore[call-arg]


# Borda
def test_coluna_extraida_sem_chaves_usa_defaults(tipo_integer: TipoDeDado) -> None:
    """Borda: coluna comum, sem chave primária/estrangeira, usa defaults False/None."""
    coluna = ColunaExtraida(nome="descricao", tipo_dado=tipo_integer)

    assert coluna.chave_primaria is False
    assert coluna.chave_estrangeira is False
    assert coluna.tabela_referenciada is None
    assert coluna.coluna_referenciada is None

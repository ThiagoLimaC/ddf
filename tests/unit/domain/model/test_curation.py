"""Testes de ColunaCurada, TabelaCurada e BancoCurado."""

import polars as pl
import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.curation import BancoCurado, ColunaCurada, TabelaCurada


# Caminho feliz
def test_cria_coluna_curada_com_papel_e_regras_de_negocio(
    tipo_integer: TipoDeDado,
) -> None:
    """Caminho feliz: ColunaCurada guarda curadoria humana sobre a estrutura."""
    coluna = ColunaCurada(
        nome="email",
        tipo_dado=tipo_integer,
        papel_de_negocio="E-mail de contato do cliente",
        regras_de_negocio=["deve ser único por tenant"],
    )

    assert coluna.papel_de_negocio == "E-mail de contato do cliente"
    assert coluna.regras_de_negocio == ["deve ser único por tenant"]


def test_cria_tabela_curada_com_amostra_e_curadoria(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Caminho feliz: TabelaCurada guarda colunas curadas, amostra e metadados."""
    tabela = TabelaCurada(
        nome_tabela="pedidos",
        nome_schema="public",
        colunas=[
            ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True)
        ],
        total_linhas=10,
        papel_de_negocio="Tabela fato de pedidos",
        amostra=amostra_df,
        metadados_amostra=metadados_de_amostra,
    )

    assert tabela.papel_de_negocio == "Tabela fato de pedidos"
    assert tabela.amostra is not None


def test_cria_banco_curado_com_multiplas_tabelas(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Caminho feliz: BancoCurado agrega múltiplas TabelaCurada distintas."""
    colunas = [ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    pedidos = TabelaCurada(
        nome_tabela="pedidos",
        nome_schema="public",
        colunas=colunas,
        total_linhas=10,
        amostra=None,
        metadados_amostra=metadados_de_amostra,
    )
    clientes = TabelaCurada(
        nome_tabela="clientes",
        nome_schema="public",
        colunas=colunas,
        total_linhas=5,
        amostra=None,
        metadados_amostra=metadados_de_amostra,
    )

    banco = BancoCurado(tabelas=[pedidos, clientes])

    assert len(banco.tabelas) == 2


# Erro esperado
def test_coluna_curada_fk_sem_referencia_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: chave_estrangeira=True sem tabela/coluna referenciada."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaCurada(nome="cliente_id", tipo_dado=tipo_integer, chave_estrangeira=True)


def test_coluna_curada_referencia_sem_fk_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: referência preenchida sem chave_estrangeira=True."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaCurada(
            nome="cliente_id",
            tipo_dado=tipo_integer,
            tabela_referenciada="clientes",
            coluna_referenciada="id",
        )


def test_tabela_curada_total_linhas_negativo_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: total_linhas negativo é logicamente impossível."""
    with pytest.raises(ValidationError, match="total_linhas"):
        TabelaCurada(
            nome_tabela="pedidos",
            nome_schema="public",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            total_linhas=-1,
            amostra=None,
            metadados_amostra=metadados_de_amostra,
        )


def test_tabela_curada_com_colunas_duplicadas_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: dois nomes de coluna iguais na mesma tabela."""
    with pytest.raises(ValidationError, match="duplicados"):
        TabelaCurada(
            nome_tabela="pedidos",
            nome_schema="public",
            colunas=[
                ColunaCurada(nome="id", tipo_dado=tipo_integer),
                ColunaCurada(nome="id", tipo_dado=tipo_integer),
            ],
            total_linhas=10,
            amostra=None,
            metadados_amostra=metadados_de_amostra,
        )


def test_banco_curado_com_tabelas_duplicadas_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: mesma (nome_schema, nome_tabela) duplicada no agregado."""
    tabela = TabelaCurada(
        nome_tabela="pedidos",
        nome_schema="public",
        colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
        total_linhas=10,
        amostra=None,
        metadados_amostra=metadados_de_amostra,
    )

    with pytest.raises(ValidationError, match="duplicadas"):
        BancoCurado(tabelas=[tabela, tabela])


# Borda
def test_coluna_curada_sem_curadoria_usa_defaults_vazios(
    tipo_integer: TipoDeDado,
) -> None:
    """Borda: coluna recém-extraída, ainda sem curadoria, usa defaults vazios."""
    coluna = ColunaCurada(nome="id", tipo_dado=tipo_integer)

    assert coluna.papel_de_negocio is None
    assert coluna.regras_de_negocio == []


def test_tabela_curada_com_amostra_none(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Borda: amostra pode ser None (mesmo DataFrame de TabelaExtraida, descartado)."""
    tabela = TabelaCurada(
        nome_tabela="pedidos",
        nome_schema="public",
        colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
        total_linhas=10,
        amostra=None,
        metadados_amostra=metadados_de_amostra,
    )

    assert tabela.amostra is None

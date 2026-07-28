"""Testes de ColunaExtraida e TabelaExtraida."""

import polars as pl
import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida


# Caminho feliz
def test_cria_coluna_extraida_com_chave_estrangeira(tipo_integer: TipoDeDado) -> None:
    """Caminho feliz: ColunaExtraida guarda referência de chave estrangeira."""
    coluna = ColunaExtraida(
        nome="cliente_id",
        tipo_dado=tipo_integer,
        chave_estrangeira=True,
        referencia=ReferenciaDeColuna(
            nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
        ),
    )

    assert coluna.chave_estrangeira is True
    assert coluna.referencia == ReferenciaDeColuna(
        nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
    )


def test_cria_tabela_extraida_com_amostra(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Caminho feliz: TabelaExtraida guarda colunas, amostra e metadados."""
    tabela = TabelaExtraida(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=[
            ColunaExtraida(nome="id", tipo_dado=tipo_integer, chave_primaria=True)
        ],
        total_linhas=10,
        amostra=amostra_df,
        metadados_amostra=metadados_de_amostra,
    )

    assert tabela.nome_tabela == "pedidos"
    assert tabela.amostra.height == 2


def test_cria_tabela_extraida_com_restricao_unica_composta(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Caminho feliz: TabelaExtraida guarda UNIQUE composto de colunas reais."""
    tabela = TabelaExtraida(
        nome_tabela="enderecos",
        nome_escopo="public",
        colunas=[
            ColunaExtraida(nome="codigo_pais", tipo_dado=tipo_integer),
            ColunaExtraida(nome="codigo_local", tipo_dado=tipo_integer),
        ],
        total_linhas=10,
        amostra=amostra_df,
        metadados_amostra=metadados_de_amostra,
        restricoes_unicas=[RestricaoUnica(colunas=("codigo_pais", "codigo_local"))],
    )

    assert tabela.restricoes_unicas == [
        RestricaoUnica(colunas=("codigo_pais", "codigo_local"))
    ]


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
            referencia=ReferenciaDeColuna(
                nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
            ),
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
            nome_escopo="public",
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
            nome_escopo="public",
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
            nome_escopo="public",
            colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
            total_linhas=10,
            amostra=None,
            metadados_amostra=metadados_de_amostra,
        )  # type: ignore[call-arg]


def test_tabela_extraida_restricao_unica_com_coluna_inexistente_e_invalida(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Erro esperado: RestricaoUnica citando coluna que a tabela não tem."""
    with pytest.raises(ValidationError, match="inexistente"):
        TabelaExtraida(
            nome_tabela="enderecos",
            nome_escopo="public",
            colunas=[ColunaExtraida(nome="codigo_pais", tipo_dado=tipo_integer)],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
            restricoes_unicas=[RestricaoUnica(colunas=("codigo_pais", "codigo_local"))],
        )


# Borda
def test_coluna_extraida_sem_chaves_usa_defaults(tipo_integer: TipoDeDado) -> None:
    """Borda: coluna comum, sem chave primária/estrangeira, usa defaults False/None."""
    coluna = ColunaExtraida(nome="descricao", tipo_dado=tipo_integer)

    assert coluna.chave_primaria is False
    assert coluna.chave_estrangeira is False
    assert coluna.referencia is None


def test_tabela_extraida_sem_restricoes_unicas_usa_lista_vazia(
    tipo_integer: TipoDeDado,
    metadados_de_amostra: MetadadosDeAmostra,
    amostra_df: pl.DataFrame,
) -> None:
    """Borda: tabela sem nenhum UNIQUE composto tem restricoes_unicas == []."""
    tabela = TabelaExtraida(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
        total_linhas=10,
        amostra=amostra_df,
        metadados_amostra=metadados_de_amostra,
    )

    assert tabela.restricoes_unicas == []

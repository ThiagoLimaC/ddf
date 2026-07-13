"""Fixtures compartilhadas dos testes de SobrescritaDeTabela."""

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida


@pytest.fixture
def tabela_extraida() -> TabelaExtraida:
    """Retorna uma TabelaExtraida simples (id + nome) para os testes de Sobrescrita."""
    return TabelaExtraida(
        nome_tabela="clientes",
        nome_schema="public",
        colunas=[
            ColunaExtraida(
                nome="id",
                tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
                chave_primaria=True,
            ),
            ColunaExtraida(
                nome="nome",
                tipo_dado=TipoDeDado(
                    categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=100
                ),
            ),
        ],
        total_linhas=3,
        amostra=pl.DataFrame({"id": [1, 2, 3], "nome": ["ana", "bia", "caio"]}),
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=3
        ),
    )

"""Testes de construir_colunas_fk."""

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.infrastructure.adapters.extractors.comum.construir_colunas_fk import (
    construir_colunas_fk,
)


class TestFeliz:
    """Caminho feliz."""

    def test_monta_dict_com_uma_referencia_por_coluna(self) -> None:
        """Cada coluna com uma única FK vira uma lista de um item."""
        linhas = [
            ("cliente_id", "vendas", "clientes", "id"),
            ("produto_id", "vendas", "produtos", "id"),
        ]

        colunas_fk = construir_colunas_fk(linhas)

        assert colunas_fk == {
            "cliente_id": [
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                )
            ],
            "produto_id": [
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="produtos", nome_coluna="id"
                )
            ],
        }


class TestBorda:
    """Bordas."""

    def test_duas_fks_na_mesma_coluna_mantem_as_duas_em_ordem(self) -> None:
        """Coluna com 2 FKs distintas (polimórfica) mantém as duas, sem descarte."""
        linhas = [
            ("entidade_id", "vendas", "clientes", "id"),
            ("entidade_id", "vendas", "fornecedores", "id"),
        ]

        colunas_fk = construir_colunas_fk(linhas)

        assert colunas_fk == {
            "entidade_id": [
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
                ),
            ]
        }

    def test_lista_de_fks_vazia_retorna_dict_vazio(self) -> None:
        """Nenhuma FK na tabela retorna dict vazio."""
        colunas_fk = construir_colunas_fk([])

        assert colunas_fk == {}

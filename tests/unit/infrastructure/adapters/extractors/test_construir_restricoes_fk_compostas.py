"""Testes de construir_restricoes_fk_compostas."""

from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.infrastructure.adapters.extractors.construir_restricoes_fk_compostas import (
    construir_restricoes_fk_compostas,
)

# Caminho feliz


def test_agrupa_duas_colunas_da_mesma_constraint() -> None:
    """Caminho feliz: 2 linhas da mesma constraint viram uma RestricaoDeFkComposta."""
    linhas = [
        ("pais_id", "geografia", "estados", "pais_id", "fk_pedidos_estado"),
        ("estado_id", "geografia", "estados", "id", "fk_pedidos_estado"),
    ]

    restricoes = construir_restricoes_fk_compostas(linhas)

    assert restricoes == [
        RestricaoDeFkComposta(
            colunas_locais=("pais_id", "estado_id"),
            nome_escopo_referenciado="geografia",
            nome_tabela_referenciada="estados",
            colunas_referenciadas=("pais_id", "id"),
        )
    ]


def test_nao_mistura_constraints_diferentes_da_mesma_tabela() -> None:
    """Caminho feliz: 2 constraints compostas distintas viram 2 restrições separadas."""
    linhas = [
        ("pais_id", "geografia", "estados", "pais_id", "fk_estado"),
        ("estado_id", "geografia", "estados", "id", "fk_estado"),
        ("ano", "vendas", "periodos", "ano", "fk_periodo"),
        ("mes", "vendas", "periodos", "mes", "fk_periodo"),
    ]

    restricoes = construir_restricoes_fk_compostas(linhas)

    assert len(restricoes) == 2
    assert {r.nome_tabela_referenciada for r in restricoes} == {"estados", "periodos"}


# Erro esperado — não se aplica: função pura, sem I/O, sem exceção esperada.


# Borda


def test_constraint_de_coluna_unica_e_ignorada() -> None:
    """Borda: FK de coluna única (grupo de 1) não vira RestricaoDeFkComposta."""
    linhas = [("cliente_id", "vendas", "clientes", "id", "fk_cliente")]

    restricoes = construir_restricoes_fk_compostas(linhas)

    assert restricoes == []


def test_lista_de_fks_vazia_retorna_lista_vazia() -> None:
    """Borda: nenhuma FK na tabela retorna lista vazia."""
    restricoes = construir_restricoes_fk_compostas([])

    assert restricoes == []

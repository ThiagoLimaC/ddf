"""Testes de construir_colunas_fk."""

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.infrastructure.adapters.extractors.construir_colunas_fk import (
    construir_colunas_fk,
)

# Caminho feliz


def test_monta_dict_sem_colisao_sem_avisos() -> None:
    """Caminho feliz: cada coluna com uma única FK não gera nenhum Aviso."""
    linhas = [
        ("cliente_id", "vendas", "clientes", "id"),
        ("produto_id", "vendas", "produtos", "id"),
    ]

    colunas_fk, avisos = construir_colunas_fk(linhas, origem="ExtratorFake")

    assert colunas_fk == {
        "cliente_id": ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
        ),
        "produto_id": ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="produtos", nome_coluna="id"
        ),
    }
    assert avisos == []


# Erro esperado — não se aplica: função pura, sem I/O, sem exceção esperada.


# Borda


def test_duas_fks_na_mesma_coluna_emite_aviso_e_mantem_a_ultima() -> None:
    """Borda: coluna com 2 FKs mantém só a última, emitindo Aviso não-fatal."""
    linhas = [
        ("entidade_id", "vendas", "clientes", "id"),
        ("entidade_id", "vendas", "fornecedores", "id"),
    ]

    colunas_fk, avisos = construir_colunas_fk(linhas, origem="ExtratorFake")

    assert colunas_fk == {
        "entidade_id": ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
        )
    }
    assert len(avisos) == 1
    assert avisos[0].origem == "ExtratorFake"
    assert "entidade_id" in avisos[0].mensagem
    assert "clientes" in avisos[0].mensagem
    assert "fornecedores" in avisos[0].mensagem


def test_lista_de_fks_vazia_retorna_dict_e_avisos_vazios() -> None:
    """Borda: nenhuma FK na tabela retorna dict e lista de avisos vazios."""
    colunas_fk, avisos = construir_colunas_fk([], origem="ExtratorFake")

    assert colunas_fk == {}
    assert avisos == []

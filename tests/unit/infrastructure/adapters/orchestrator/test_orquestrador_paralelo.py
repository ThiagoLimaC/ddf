"""Testes de OrquestradorParalelo."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from ddf.domain.model.curation import BancoCurado
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.orchestrator.orquestrador_paralelo import (
    OrquestradorParalelo,
)

if TYPE_CHECKING:
    from .conftest import ExtratorFake, SobrescritaFake

# Caminho feliz


def test_extrair_lista_e_extrai_tabelas_ordenadas(
    construir_extrator_fake: Callable[..., ExtratorFake],
) -> None:
    """Caminho feliz: extrai tabelas de múltiplos escopos, resultado ordenado."""
    extrator = construir_extrator_fake(
        {
            "vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")]),
            "estoque": Sucesso([("estoque", "produtos")]),
        }
    )
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.extrair(["vendas", "estoque"], extrator)

    assert isinstance(resultado, Sucesso)
    identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor]
    assert identificadores == [
        ("estoque", "produtos"),
        ("vendas", "clientes"),
        ("vendas", "pedidos"),
    ]


def test_aplicar_sobrescritas_agrega_banco_curado_ordenado(
    fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    construir_sobrescrita_fake: Callable[..., SobrescritaFake],
) -> None:
    """Caminho feliz: aplica Sobrescrita em paralelo, BancoCurado ordenado."""
    tabelas = [
        fabrica_tabela_extraida("vendas", "pedidos"),
        fabrica_tabela_extraida("estoque", "produtos"),
        fabrica_tabela_extraida("vendas", "clientes"),
    ]
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.aplicar_sobrescritas(tabelas, construir_sobrescrita_fake())

    assert isinstance(resultado, Sucesso)
    assert isinstance(resultado.valor, BancoCurado)
    identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor.tabelas]
    assert identificadores == [
        ("estoque", "produtos"),
        ("vendas", "clientes"),
        ("vendas", "pedidos"),
    ]


# Erro esperado


def test_max_trabalhadores_zero_levanta_value_error() -> None:
    """Erro esperado: max_trabalhadores=0 quebraria o ThreadPoolExecutor — rejeitado."""
    with pytest.raises(ValueError, match="max_trabalhadores"):
        OrquestradorParalelo(max_trabalhadores=0)


def test_extrair_com_tabela_com_falha_retorna_falha_agregada(
    construir_extrator_fake: Callable[..., ExtratorFake],
) -> None:
    """Erro esperado: uma tabela falha entre várias — Falha agregada, sem parcial."""
    extrator = construir_extrator_fake(
        {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")])},
        {("vendas", "clientes"): "conexão perdida"},
    )
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.extrair(["vendas"], extrator)

    assert isinstance(resultado, Falha)
    assert "Falha ao extrair 1 de 2 tabelas" in resultado.erro
    assert "vendas.clientes: conexão perdida" in resultado.erro


def test_extrair_com_excecao_nao_prevista_acumula_como_falha(
    construir_extrator_fake: Callable[..., ExtratorFake],
) -> None:
    """Erro esperado: Exception não prevista dentro do worker vira Falha isolada.

    Reproduz o boundary sistemático da issue #56 — sem executar_com_seguranca
    em volta da chamada no worker, isso propagaria crua via futuro.result(),
    quebrando a extração inteira em vez de virar uma falha isolada, acumulada
    como as demais (mesma política de 'não interrompe os outros workers').
    """
    extrator = construir_extrator_fake(
        {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")])},
        excecoes_de_extracao={
            ("vendas", "clientes"): ValueError("dtype não suportado")
        },
    )
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.extrair(["vendas"], extrator)

    assert isinstance(resultado, Falha)
    assert "Falha ao extrair 1 de 2 tabelas" in resultado.erro
    assert "vendas.clientes" in resultado.erro
    assert "ValueError" in resultado.erro
    assert "dtype não suportado" in resultado.erro


def test_extrair_com_falha_de_listagem_de_escopo_acumula(
    construir_extrator_fake: Callable[..., ExtratorFake],
) -> None:
    """Erro esperado: escopo com erro de listagem acumula, não aborta os demais."""
    extrator = construir_extrator_fake(
        {
            "vendas": Sucesso([("vendas", "pedidos")]),
            "financeiro_typo": Falha("Escopo 'financeiro_typo' não encontrado."),
        }
    )
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.extrair(["vendas", "financeiro_typo"], extrator)

    assert isinstance(resultado, Falha)
    assert "Falha ao extrair 1 de 2 tabelas" in resultado.erro
    assert "financeiro_typo: Escopo 'financeiro_typo' não encontrado." in resultado.erro


def test_aplicar_sobrescritas_com_falha_retorna_falha_agregada(
    fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    construir_sobrescrita_fake: Callable[..., SobrescritaFake],
) -> None:
    """Erro esperado: uma sobrescrita falha entre várias — Falha agregada."""
    tabelas = [
        fabrica_tabela_extraida("vendas", "pedidos"),
        fabrica_tabela_extraida("vendas", "clientes"),
    ]
    sobrescrita = construir_sobrescrita_fake(
        {("vendas", "clientes"): "YAML malformado"}
    )
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita)

    assert isinstance(resultado, Falha)
    assert "Falha ao aplicar sobrescritas em 1 de 2 tabelas" in resultado.erro
    assert "vendas.clientes: YAML malformado" in resultado.erro


# Borda


def test_extrair_lista_de_escopos_vazia_retorna_sucesso_vazio(
    construir_extrator_fake: Callable[..., ExtratorFake],
) -> None:
    """Borda: lista de escopos vazia retorna Sucesso com lista vazia."""
    extrator = construir_extrator_fake({})
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado: Resultado[list[TabelaExtraida]] = orquestrador.extrair([], extrator)

    assert resultado == Sucesso([])


def test_aplicar_sobrescritas_lista_vazia_retorna_banco_curado_vazio(
    construir_sobrescrita_fake: Callable[..., SobrescritaFake],
) -> None:
    """Borda: lista de tabelas vazia retorna Sucesso com BancoCurado vazio."""
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.aplicar_sobrescritas([], construir_sobrescrita_fake())

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == BancoCurado(tabelas=[])

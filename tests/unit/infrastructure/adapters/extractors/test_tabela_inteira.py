"""Testes de TabelaInteira."""

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemIntegral
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.tabela_inteira import TabelaInteira

# Caminho feliz


def test_tabela_inteira_satisfaz_estrategia_de_amostragem() -> None:
    """Caminho feliz: TabelaInteira conforma ao Port EstrategiaDeAmostragem."""
    assert isinstance(TabelaInteira(), EstrategiaDeAmostragem)


def test_nome_retorna_tabela_inteira() -> None:
    """Caminho feliz: nome identifica a estratégia como 'tabela_inteira'."""
    assert TabelaInteira().nome == "tabela_inteira"


def test_requisicao_retorna_amostragem_integral() -> None:
    """Caminho feliz: requisicao é sempre AmostragemIntegral, sem parâmetros."""
    assert TabelaInteira().requisicao == AmostragemIntegral()


# Erro esperado — não se aplica: TabelaInteira não tem parâmetros pra validar.


# Borda


def test_duas_instancias_sao_equivalentes() -> None:
    """Borda: sem estado, duas instâncias produzem a mesma requisicao."""
    assert TabelaInteira().requisicao == TabelaInteira().requisicao

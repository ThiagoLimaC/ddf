"""Testes de FullScan."""

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemIntegral
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.full_scan import FullScan

# Caminho feliz


def test_full_scan_satisfaz_estrategia_de_amostragem() -> None:
    """Caminho feliz: FullScan conforma ao Port EstrategiaDeAmostragem."""
    assert isinstance(FullScan(), EstrategiaDeAmostragem)


def test_nome_retorna_full_scan() -> None:
    """Caminho feliz: nome identifica a estratégia como 'full_scan'."""
    assert FullScan().nome == "full_scan"


def test_requisicao_retorna_amostragem_integral() -> None:
    """Caminho feliz: requisicao é sempre AmostragemIntegral, sem parâmetros."""
    assert FullScan().requisicao == AmostragemIntegral()


# Erro esperado — não se aplica: FullScan não tem parâmetros pra validar.


# Borda


def test_duas_instancias_sao_equivalentes() -> None:
    """Borda: sem estado, duas instâncias de FullScan produzem a mesma requisicao."""
    assert FullScan().requisicao == FullScan().requisicao

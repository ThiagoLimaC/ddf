"""Testes de ConfiguracaoDeExtracao."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.domain.shared.resultado import Falha, Sucesso


def test_cria_configuracao_com_estrategia(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Caminho feliz: ConfiguracaoDeExtracao aceita a estrategia informada."""
    configuracao = ConfiguracaoDeExtracao(estrategia=estrategia_fake)

    assert configuracao.estrategia is estrategia_fake


def test_estrategia_que_nao_implementa_protocol_e_rejeitada() -> None:
    """Erro esperado: objeto sem 'nome'/'percentual' não satisfaz o Protocol."""
    with pytest.raises(ValidationError):
        ConfiguracaoDeExtracao(estrategia=object())  # type: ignore[arg-type]


# estrategia_obrigatoria() — caminho feliz, erro esperado, borda


def test_estrategia_obrigatoria_com_estrategia_configurada_devolve_sucesso(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Caminho feliz: estrategia já configurada devolve Sucesso com ela."""
    configuracao = ConfiguracaoDeExtracao(estrategia=estrategia_fake)

    resultado = configuracao.estrategia_obrigatoria()

    assert isinstance(resultado, Sucesso)
    assert resultado.valor is estrategia_fake


def test_estrategia_obrigatoria_sem_estrategia_devolve_falha() -> None:
    """Erro esperado: estrategia ainda None (não configurada) devolve Falha.

    Reproduz o construtor de Extrator do wizard (`etapas/extracao.py::
    conectar`), que cria ConfiguracaoDeExtracao antes de a estratégia de
    amostragem ser escolhida — este é o guard que os dois Extratores
    concretos usam em vez de reimplementar o `if estrategia is None`.
    """
    configuracao = ConfiguracaoDeExtracao()

    resultado = configuracao.estrategia_obrigatoria()

    assert isinstance(resultado, Falha)
    assert "sem estratégia" in resultado.erro


def test_estrategia_obrigatoria_apos_atribuicao_tardia_devolve_sucesso(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Borda: estrategia atribuída depois da construção (mutação) já é vista.

    Reproduz o padrão real do wizard: `conectar()` cria a configuração sem
    estratégia, `configurar_amostragem()` atribui depois — mesma instância.
    """
    configuracao = ConfiguracaoDeExtracao()

    configuracao.estrategia = estrategia_fake
    resultado = configuracao.estrategia_obrigatoria()

    assert isinstance(resultado, Sucesso)
    assert resultado.valor is estrategia_fake

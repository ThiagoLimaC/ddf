"""Testes de TabelaInteira."""

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemIntegral
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.tabela_inteira import (
    TabelaInteira,
)


class TestFeliz:
    """Caminho feliz."""

    def test_tabela_inteira_satisfaz_estrategia_de_amostragem(
        self,
    ) -> None:
        """TabelaInteira conforma ao Port EstrategiaDeAmostragem."""
        assert isinstance(TabelaInteira(), EstrategiaDeAmostragem)

    def test_nome_retorna_tabela_inteira(
        self,
    ) -> None:
        """Nome identifica a estratégia como 'tabela_inteira'."""
        assert TabelaInteira().nome == "tabela_inteira"

    def test_requisicao_retorna_amostragem_integral(
        self,
    ) -> None:
        """Requisicao é sempre AmostragemIntegral, sem parâmetros."""
        assert TabelaInteira().requisicao == AmostragemIntegral()


class TestBorda:
    """Bordas."""

    def test_duas_instancias_sao_equivalentes(
        self,
    ) -> None:
        """Sem estado, duas instâncias produzem a mesma requisicao."""
        assert TabelaInteira().requisicao == TabelaInteira().requisicao

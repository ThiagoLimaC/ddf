"""Testes de ConfiguracaoDeExtracao."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.domain.shared.resultado import Falha, Sucesso


class TestFeliz:
    """Caminho feliz."""

    def test_cria_configuracao_com_estrategia(
        self, estrategia_fake: EstrategiaDeAmostragem
    ) -> None:
        """ConfiguracaoDeExtracao aceita a estrategia informada."""
        configuracao = ConfiguracaoDeExtracao(estrategia=estrategia_fake)

        assert configuracao.estrategia is estrategia_fake

    def test_estrategia_obrigatoria_com_estrategia_configurada_devolve_sucesso(
        self, estrategia_fake: EstrategiaDeAmostragem
    ) -> None:
        """estrategia_obrigatoria() com estrategia já configurada devolve Sucesso."""
        configuracao = ConfiguracaoDeExtracao(estrategia=estrategia_fake)

        resultado = configuracao.estrategia_obrigatoria()

        assert isinstance(resultado, Sucesso)
        assert resultado.valor is estrategia_fake


class TestErro:
    """Erro esperado."""

    def test_estrategia_que_nao_implementa_protocol_e_rejeitada(self) -> None:
        """Objeto sem 'nome'/'percentual' não satisfaz o Protocol."""
        with pytest.raises(ValidationError):
            ConfiguracaoDeExtracao(estrategia=object())  # type: ignore[arg-type]

    def test_estrategia_obrigatoria_sem_estrategia_devolve_falha(self) -> None:
        """estrategia_obrigatoria() com estrategia ainda None devolve Falha.

        Reproduz o construtor de Extrator do wizard (`etapas/extracao.py::
        conectar`), que cria ConfiguracaoDeExtracao antes de a estratégia de
        amostragem ser escolhida — este é o guard que os dois Extratores
        concretos usam em vez de reimplementar o `if estrategia is None`.
        """
        configuracao = ConfiguracaoDeExtracao()

        resultado = configuracao.estrategia_obrigatoria()

        assert isinstance(resultado, Falha)
        assert "sem estratégia" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_estrategia_obrigatoria_apos_atribuicao_tardia_devolve_sucesso(
        self, estrategia_fake: EstrategiaDeAmostragem
    ) -> None:
        """estrategia_obrigatoria() vê estrategia atribuída depois da construção.

        Reproduz o padrão real do wizard: `conectar()` cria a configuração sem
        estratégia, `configurar_amostragem()` atribui depois — mesma instância.
        """
        configuracao = ConfiguracaoDeExtracao()

        configuracao.estrategia = estrategia_fake
        resultado = configuracao.estrategia_obrigatoria()

        assert isinstance(resultado, Sucesso)
        assert resultado.valor is estrategia_fake

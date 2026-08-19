"""Testes de PercentualDeLinhas."""

import pytest
from pydantic import ValidationError

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)


class TestFeliz:
    """Caminho feliz."""

    def test_percentual_de_linhas_satisfaz_estrategia_de_amostragem(
        self,
        percentual_de_linhas: PercentualDeLinhas,
    ) -> None:
        """PercentualDeLinhas conforma ao Port EstrategiaDeAmostragem."""
        assert isinstance(percentual_de_linhas, EstrategiaDeAmostragem)

    def test_percentual_retorna_valor_configurado(
        self,
        percentual_de_linhas: PercentualDeLinhas,
    ) -> None:
        """Percentual guarda o valor informado na construção."""
        assert percentual_de_linhas.requisicao.percentual == 10.0

    def test_seed_e_opcional_e_default_para_none(
        self,
        percentual_de_linhas: PercentualDeLinhas,
    ) -> None:
        """Sem seed informado, requisicao.seed é None."""
        assert percentual_de_linhas.requisicao.seed is None

    def test_seed_informado_e_guardado_na_requisicao(
        self,
    ) -> None:
        """Seed informado na construção chega em requisicao.seed."""
        estrategia = PercentualDeLinhas(percentual=10.0, seed=42)

        assert estrategia.requisicao.seed == 42

    def test_nome_retorna_percentual_de_linhas(
        self,
        percentual_de_linhas: PercentualDeLinhas,
    ) -> None:
        """Nome identifica a estratégia como 'percentual_de_linhas'."""
        assert percentual_de_linhas.nome == "percentual_de_linhas"


class TestErro:
    """Erro esperado."""

    def test_percentual_zero_levanta_validation_error(
        self,
    ) -> None:
        """percentual=0 está fora do intervalo (0, 100]."""
        with pytest.raises(ValidationError, match="percentual"):
            PercentualDeLinhas(percentual=0)

    def test_percentual_acima_de_cem_levanta_validation_error(
        self,
    ) -> None:
        """percentual>100 não representa uma fração da tabela."""
        with pytest.raises(ValidationError, match="percentual"):
            PercentualDeLinhas(percentual=101)

    def test_percentual_negativo_levanta_validation_error(
        self,
    ) -> None:
        """Percentual negativo não faz sentido."""
        with pytest.raises(ValidationError, match="percentual"):
            PercentualDeLinhas(percentual=-5)


class TestBorda:
    """Bordas."""

    def test_percentual_cem_e_aceito(
        self,
    ) -> None:
        """percentual=100, maior valor válido, amostra a tabela inteira."""
        estrategia = PercentualDeLinhas(percentual=100)

        assert estrategia.requisicao.percentual == 100

"""Testes de AmostragemProbabilistica, AmostragemIntegral e RequisicaoPorFaixa."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoPorFaixa,
)


class TestFeliz:
    """Caminho feliz."""

    def test_amostragem_probabilistica_guarda_percentual_e_seed(self) -> None:
        """AmostragemProbabilistica guarda percentual e seed."""
        requisicao = AmostragemProbabilistica(percentual=10.0, seed=42)

        assert requisicao.percentual == 10.0
        assert requisicao.seed == 42

    def test_amostragem_probabilistica_seed_e_opcional(self) -> None:
        """Seed não informado é None (não reprodutível por padrão)."""
        requisicao = AmostragemProbabilistica(percentual=10.0)

        assert requisicao.seed is None

    def test_amostragem_integral_nao_tem_parametros(self) -> None:
        """AmostragemIntegral não carrega nenhum parâmetro."""
        requisicao = AmostragemIntegral()

        assert requisicao == AmostragemIntegral()

    def test_requisicao_por_faixa_guarda_percentual_e_seed(self) -> None:
        """RequisicaoPorFaixa guarda percentual e seed."""
        requisicao = RequisicaoPorFaixa(percentual=10.0, seed=42)

        assert requisicao.percentual == 10.0
        assert requisicao.seed == 42

    def test_requisicao_por_faixa_seed_e_opcional(self) -> None:
        """Seed não informado é None (não reprodutível por padrão)."""
        requisicao = RequisicaoPorFaixa(percentual=10.0)

        assert requisicao.seed is None


class TestErro:
    """Erro esperado."""

    def test_amostragem_probabilistica_percentual_zero_levanta_validation_error(
        self,
    ) -> None:
        """percentual=0 está fora do intervalo (0, 100]."""
        with pytest.raises(ValidationError, match="percentual"):
            AmostragemProbabilistica(percentual=0)

    def test_amostragem_probabilistica_percentual_acima_de_cem_e_invalido(self) -> None:
        """percentual>100 não representa uma fração da tabela."""
        with pytest.raises(ValidationError, match="percentual"):
            AmostragemProbabilistica(percentual=101)

    def test_requisicao_por_faixa_percentual_zero_levanta_validation_error(
        self,
    ) -> None:
        """percentual=0 está fora do intervalo (0, 100]."""
        with pytest.raises(ValidationError, match="percentual"):
            RequisicaoPorFaixa(percentual=0)


class TestBorda:
    """Bordas."""

    def test_amostragem_probabilistica_e_imutavel(self) -> None:
        """AmostragemProbabilistica é imutável após construção (frozen=True)."""
        requisicao = AmostragemProbabilistica(percentual=10.0)

        with pytest.raises(ValidationError):
            requisicao.percentual = 20.0

    def test_amostragem_probabilistica_percentual_cem_e_aceito(self) -> None:
        """percentual=100, maior valor válido, amostra a tabela inteira."""
        requisicao = AmostragemProbabilistica(percentual=100)

        assert requisicao.percentual == 100

    def test_requisicao_por_faixa_e_imutavel(self) -> None:
        """RequisicaoPorFaixa é imutável após construção (frozen=True)."""
        requisicao = RequisicaoPorFaixa(percentual=10.0)

        with pytest.raises(ValidationError):
            requisicao.percentual = 20.0

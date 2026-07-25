"""Testes de AmostragemProbabilistica e AmostragemIntegral."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
)

# Caminho feliz


def test_amostragem_probabilistica_guarda_percentual_e_seed() -> None:
    """Caminho feliz: AmostragemProbabilistica guarda percentual e seed."""
    requisicao = AmostragemProbabilistica(percentual=10.0, seed=42)

    assert requisicao.percentual == 10.0
    assert requisicao.seed == 42


def test_amostragem_probabilistica_seed_e_opcional() -> None:
    """Caminho feliz: seed não informado é None (não reprodutível por padrão)."""
    requisicao = AmostragemProbabilistica(percentual=10.0)

    assert requisicao.seed is None


def test_amostragem_integral_nao_tem_parametros() -> None:
    """Caminho feliz: AmostragemIntegral não carrega nenhum parâmetro."""
    requisicao = AmostragemIntegral()

    assert requisicao == AmostragemIntegral()


# Erro esperado


def test_amostragem_probabilistica_percentual_zero_levanta_validation_error() -> None:
    """Erro esperado: percentual=0 está fora do intervalo (0, 100]."""
    with pytest.raises(ValidationError, match="percentual"):
        AmostragemProbabilistica(percentual=0)


def test_amostragem_probabilistica_percentual_acima_de_cem_e_invalido() -> None:
    """Erro esperado: percentual>100 não representa uma fração da tabela."""
    with pytest.raises(ValidationError, match="percentual"):
        AmostragemProbabilistica(percentual=101)


# Borda


def test_amostragem_probabilistica_e_imutavel() -> None:
    """Borda: AmostragemProbabilistica é imutável após construção (frozen=True)."""
    requisicao = AmostragemProbabilistica(percentual=10.0)

    with pytest.raises(ValidationError):
        requisicao.percentual = 20.0


def test_amostragem_probabilistica_percentual_cem_e_aceito() -> None:
    """Borda: percentual=100, maior valor válido, amostra a tabela inteira."""
    requisicao = AmostragemProbabilistica(percentual=100)

    assert requisicao.percentual == 100

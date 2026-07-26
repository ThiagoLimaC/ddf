"""Testes de PercentualDeLinhas."""

import pytest
from pydantic import ValidationError

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)

# Caminho feliz


def test_percentual_de_linhas_satisfaz_estrategia_de_amostragem(
    percentual_de_linhas: PercentualDeLinhas,
) -> None:
    """Caminho feliz: PercentualDeLinhas conforma ao Port EstrategiaDeAmostragem."""
    assert isinstance(percentual_de_linhas, EstrategiaDeAmostragem)


def test_percentual_retorna_valor_configurado(
    percentual_de_linhas: PercentualDeLinhas,
) -> None:
    """Caminho feliz: percentual guarda o valor informado na construção."""
    assert percentual_de_linhas.requisicao.percentual == 10.0


def test_seed_e_opcional_e_default_para_none(
    percentual_de_linhas: PercentualDeLinhas,
) -> None:
    """Caminho feliz: sem seed informado, requisicao.seed é None."""
    assert percentual_de_linhas.requisicao.seed is None


def test_seed_informado_e_guardado_na_requisicao() -> None:
    """Caminho feliz: seed informado na construção chega em requisicao.seed."""
    estrategia = PercentualDeLinhas(percentual=10.0, seed=42)

    assert estrategia.requisicao.seed == 42


def test_nome_retorna_percentual_de_linhas(
    percentual_de_linhas: PercentualDeLinhas,
) -> None:
    """Caminho feliz: nome identifica a estratégia como 'percentual_de_linhas'."""
    assert percentual_de_linhas.nome == "percentual_de_linhas"


# Erro esperado


def test_percentual_zero_levanta_validation_error() -> None:
    """Erro esperado: percentual=0 está fora do intervalo (0, 100]."""
    with pytest.raises(ValidationError, match="percentual"):
        PercentualDeLinhas(percentual=0)


def test_percentual_acima_de_cem_levanta_validation_error() -> None:
    """Erro esperado: percentual>100 não representa uma fração da tabela."""
    with pytest.raises(ValidationError, match="percentual"):
        PercentualDeLinhas(percentual=101)


def test_percentual_negativo_levanta_validation_error() -> None:
    """Erro esperado: percentual negativo não faz sentido."""
    with pytest.raises(ValidationError, match="percentual"):
        PercentualDeLinhas(percentual=-5)


# Borda


def test_percentual_cem_e_aceito() -> None:
    """Borda: percentual=100, maior valor válido, amostra a tabela inteira."""
    estrategia = PercentualDeLinhas(percentual=100)

    assert estrategia.requisicao.percentual == 100

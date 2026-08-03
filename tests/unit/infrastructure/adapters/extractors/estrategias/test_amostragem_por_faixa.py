"""Testes de AmostragemPorFaixa."""

import pytest
from pydantic import ValidationError

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.estrategias.amostragem_por_faixa import (
    AmostragemPorFaixa,
)


class TestFeliz:
    """Caminho feliz."""

    def test_amostragem_por_faixa_satisfaz_estrategia_de_amostragem(self) -> None:
        """AmostragemPorFaixa conforma ao Port EstrategiaDeAmostragem."""
        assert isinstance(AmostragemPorFaixa(percentual=10.0), EstrategiaDeAmostragem)

    def test_percentual_retorna_valor_configurado(self) -> None:
        """Percentual guarda o valor informado na construção."""
        estrategia = AmostragemPorFaixa(percentual=10.0)

        assert estrategia.requisicao.percentual == 10.0

    def test_seed_e_opcional_e_default_para_none(self) -> None:
        """Sem seed informado, requisicao.seed é None."""
        estrategia = AmostragemPorFaixa(percentual=10.0)

        assert estrategia.requisicao.seed is None

    def test_seed_informado_e_guardado_na_requisicao(self) -> None:
        """Seed informado na construção chega em requisicao.seed."""
        estrategia = AmostragemPorFaixa(percentual=10.0, seed=42)

        assert estrategia.requisicao.seed == 42

    def test_nome_retorna_amostragem_por_faixa(self) -> None:
        """Nome identifica a estratégia como 'amostragem_por_faixa'."""
        assert AmostragemPorFaixa(percentual=10.0).nome == "amostragem_por_faixa"


class TestErro:
    """Erro esperado."""

    def test_percentual_zero_levanta_validation_error(self) -> None:
        """percentual=0 está fora do intervalo (0, 100]."""
        with pytest.raises(ValidationError, match="percentual"):
            AmostragemPorFaixa(percentual=0)

    def test_percentual_acima_de_cem_levanta_validation_error(self) -> None:
        """percentual>100 não representa uma fração da tabela."""
        with pytest.raises(ValidationError, match="percentual"):
            AmostragemPorFaixa(percentual=101)

    def test_percentual_negativo_levanta_validation_error(self) -> None:
        """Percentual negativo não faz sentido."""
        with pytest.raises(ValidationError, match="percentual"):
            AmostragemPorFaixa(percentual=-5)


class TestBorda:
    """Bordas."""

    def test_percentual_cem_e_aceito(self) -> None:
        """percentual=100, maior valor válido, amostra a tabela inteira por faixas."""
        estrategia = AmostragemPorFaixa(percentual=100)

        assert estrategia.requisicao.percentual == 100

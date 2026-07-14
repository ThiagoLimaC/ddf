"""Testes de ConfiguracaoDeExtracao."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem


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

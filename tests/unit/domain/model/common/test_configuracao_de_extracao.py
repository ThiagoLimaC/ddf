"""Testes de ConfiguracaoDeExtracao."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem


def test_cria_configuracao_com_estrategia_e_defaults(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Caminho feliz: ConfiguracaoDeExtracao aceita a estrategia e usa defaults."""
    configuracao = ConfiguracaoDeExtracao(estrategia=estrategia_fake)

    assert configuracao.estrategia is estrategia_fake
    assert configuracao.max_trabalhadores == 8
    assert configuracao.max_conexoes == 10


def test_max_conexoes_menor_que_trabalhadores_levanta_validation_error(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Erro esperado: max_conexoes < max_trabalhadores é rejeitado com clareza."""
    with pytest.raises(ValidationError, match="max_conexoes"):
        ConfiguracaoDeExtracao(
            estrategia=estrategia_fake, max_trabalhadores=8, max_conexoes=4
        )


def test_max_conexoes_igual_a_trabalhadores_e_aceito(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Borda: max_conexoes == max_trabalhadores satisfaz a validação (limite exato)."""
    configuracao = ConfiguracaoDeExtracao(
        estrategia=estrategia_fake, max_trabalhadores=8, max_conexoes=8
    )

    assert configuracao.max_conexoes == configuracao.max_trabalhadores


def test_estrategia_que_nao_implementa_protocol_e_rejeitada() -> None:
    """Borda: objeto sem 'nome'/'consulta' não satisfaz o Protocol via InstanceOf."""
    with pytest.raises(ValidationError):
        ConfiguracaoDeExtracao(estrategia=object())  # type: ignore[arg-type]


def test_max_trabalhadores_zero_levanta_validation_error(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Erro esperado: zero trabalhadores torna a extração inútil."""
    with pytest.raises(ValidationError, match="max_trabalhadores"):
        ConfiguracaoDeExtracao(
            estrategia=estrategia_fake, max_trabalhadores=0, max_conexoes=1
        )


def test_max_conexoes_negativo_levanta_validation_error(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Erro esperado: max_conexoes negativo não tem sentido operacional."""
    with pytest.raises(ValidationError, match="max_conexoes"):
        ConfiguracaoDeExtracao(
            estrategia=estrategia_fake, max_trabalhadores=1, max_conexoes=-1
        )


def test_max_trabalhadores_e_max_conexoes_iguais_a_um_e_aceito(
    estrategia_fake: EstrategiaDeAmostragem,
) -> None:
    """Borda: 1 trabalhador e 1 conexão é o menor valor operacionalmente válido."""
    configuracao = ConfiguracaoDeExtracao(
        estrategia=estrategia_fake, max_trabalhadores=1, max_conexoes=1
    )

    assert configuracao.max_trabalhadores == 1
    assert configuracao.max_conexoes == 1

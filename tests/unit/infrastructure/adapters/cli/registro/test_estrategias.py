"""Testes de registrar_estrategia."""

import pytest

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemProbabilistica
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.cli.registro.estrategias import (
    ESTRATEGIAS_REGISTRADAS,
    EstrategiaRegistrada,
    registrar_estrategia,
)


class EstrategiaFake:
    """Estratégia fake usada só para popular o registro nos testes."""

    @property
    def nome(self) -> str:
        """Não é exercitado por registrar_estrategia — não precisa de corpo real."""
        return "fake"

    @property
    def requisicao(self) -> AmostragemProbabilistica:
        """Não é exercitado por registrar_estrategia — não precisa de corpo real."""
        return AmostragemProbabilistica(percentual=10.0)


def _construir_fake() -> EstrategiaDeAmostragem:
    """Construtor fake usado só para popular o registro nos testes."""
    return EstrategiaFake()


# Caminho feliz
def test_registrar_estrategia_em_registro_isolado_nao_afeta_o_global() -> None:
    """Caminho feliz: registro isolado recebe a estratégia, o global não muda."""
    registro_de_teste: dict[str, EstrategiaRegistrada] = {}

    registrar_estrategia("Fake", _construir_fake, registro=registro_de_teste)

    assert registro_de_teste == {
        "Fake": EstrategiaRegistrada(construir=_construir_fake)
    }
    assert "Fake" not in ESTRATEGIAS_REGISTRADAS


# Erro esperado
def test_registrar_estrategia_com_nome_duplicado_falha() -> None:
    """Erro esperado: nome já registrado levanta ValueError, sem sobrescrever."""
    registro_de_teste: dict[str, EstrategiaRegistrada] = {
        "Fake": EstrategiaRegistrada(construir=_construir_fake)
    }

    with pytest.raises(ValueError, match="Fake"):
        registrar_estrategia("Fake", _construir_fake, registro=registro_de_teste)

    assert registro_de_teste == {
        "Fake": EstrategiaRegistrada(construir=_construir_fake)
    }

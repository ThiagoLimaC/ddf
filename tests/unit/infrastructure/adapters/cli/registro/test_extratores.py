"""Testes de registrar_extrator."""

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator
from ddf.infrastructure.adapters.cli.registro.extratores import (
    EXTRATORES_REGISTRADOS,
    ExtratorRegistrado,
    registrar_extrator,
)


class ExtratorFake:
    """Extrator fake usado só para popular o registro nos testes."""

    def listar_escopos(self) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...

    def listar_tabelas(self, escopo: str) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...

    def extrair_tabela(self, escopo: str, tabela: str) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...


def _construir_fake(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Construtor fake usado só para popular o registro nos testes."""
    return ExtratorFake()


# Caminho feliz
def test_registrar_extrator_em_registro_isolado_nao_afeta_o_global() -> None:
    """Caminho feliz: registro isolado recebe o Extrator, o global não muda."""
    registro_de_teste: dict[str, ExtratorRegistrado] = {}

    registrar_extrator(
        "Fake", ExtratorFake, _construir_fake, registro=registro_de_teste
    )

    assert registro_de_teste == {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }
    assert "Fake" not in EXTRATORES_REGISTRADOS


# Erro esperado
def test_registrar_extrator_com_nome_duplicado_falha() -> None:
    """Erro esperado: nome já registrado levanta ValueError, sem sobrescrever."""
    registro_de_teste: dict[str, ExtratorRegistrado] = {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }

    with pytest.raises(ValueError, match="Fake"):
        registrar_extrator(
            "Fake", ExtratorFake, _construir_fake, registro=registro_de_teste
        )

    assert registro_de_teste == {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }

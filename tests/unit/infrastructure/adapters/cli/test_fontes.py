"""Testes de registrar_fonte."""

import pytest

from ddf.domain.ports.extrator import Extrator
from ddf.infrastructure.adapters.cli.fontes import FONTES_REGISTRADAS, registrar_fonte


class ExtratorFake:
    """Extrator fake usado só para popular o registro nos testes."""

    def listar_tabelas(self, schema: str) -> object:
        """Não é exercitado por registrar_fonte — não precisa de corpo real."""
        raise NotImplementedError

    def extrair_tabela(self, schema: str, tabela: str) -> object:
        """Não é exercitado por registrar_fonte — não precisa de corpo real."""
        raise NotImplementedError


# Caminho feliz
def test_registrar_fonte_em_registro_isolado_nao_afeta_o_global() -> None:
    """Caminho feliz: registro isolado recebe a fonte, FONTES_REGISTRADAS não muda."""
    registro_de_teste: dict[str, type[Extrator]] = {}

    registrar_fonte("Fake", ExtratorFake, registro=registro_de_teste)

    assert registro_de_teste == {"Fake": ExtratorFake}
    assert "Fake" not in FONTES_REGISTRADAS


# Erro esperado
def test_registrar_fonte_com_nome_duplicado_falha() -> None:
    """Erro esperado: nome já registrado levanta ValueError, sem sobrescrever."""
    registro_de_teste: dict[str, type[Extrator]] = {"Fake": ExtratorFake}

    with pytest.raises(ValueError, match="Fake"):
        registrar_fonte("Fake", ExtratorFake, registro=registro_de_teste)

    assert registro_de_teste == {"Fake": ExtratorFake}

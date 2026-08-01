"""Testes de registrar_analisador."""

import pytest

from ddf.domain.model.analysis import ContextoDeAnalise, TipoDeMetrica
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Resultado
from ddf.infrastructure.adapters.cli.registro.analisadores import (
    ANALISADORES_REGISTRADOS,
    registrar_analisador,
)


class AnalisadorFake:
    """Analisador fake usado só para popular o registro nos testes."""

    produz: list[TipoDeMetrica] = []
    requer: list[TipoDeMetrica] = []

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
        """Não é exercitado por registrar_analisador — não precisa de corpo real."""
        ...


class TestFeliz:
    """Caminho feliz."""

    def test_registrar_analisador_em_registro_isolado_nao_afeta_o_global(
        self,
    ) -> None:
        """Registro isolado recebe o Analisador, o global não muda."""
        analisador = AnalisadorFake()
        registro_de_teste: dict[str, Analisador] = {}

        registrar_analisador("Fake", analisador, registro=registro_de_teste)

        assert registro_de_teste == {"Fake": analisador}
        assert "Fake" not in ANALISADORES_REGISTRADOS


class TestErro:
    """Erro esperado."""

    def test_registrar_analisador_com_nome_duplicado_falha(
        self,
    ) -> None:
        """Nome já registrado levanta ValueError, sem sobrescrever."""
        analisador = AnalisadorFake()
        registro_de_teste: dict[str, Analisador] = {"Fake": analisador}

        with pytest.raises(ValueError, match="Fake"):
            registrar_analisador("Fake", AnalisadorFake(), registro=registro_de_teste)

        assert registro_de_teste == {"Fake": analisador}

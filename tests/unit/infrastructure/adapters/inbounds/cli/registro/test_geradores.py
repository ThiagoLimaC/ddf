"""Testes de registrar_gerador."""

from pathlib import Path

import pytest

from ddf.domain.model.analysis import BancoAnalisado, TipoDeMetrica
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.resultado import Resultado
from ddf.infrastructure.adapters.inbounds.cli.registro.geradores import (
    GERADORES_REGISTRADOS,
    registrar_gerador,
)


class GeradorFake:
    """Gerador fake usado só para popular o registro nos testes."""

    requer: list[TipoDeMetrica] = []

    def __call__(
        self, entrada: BancoAnalisado, destino: Path, /
    ) -> Resultado[None]:
        """Não é exercitado por registrar_gerador — não precisa de corpo real."""
        raise NotImplementedError


class TestFeliz:
    """Caminho feliz."""

    def test_registrar_gerador_em_registro_isolado_nao_afeta_o_global(
        self,
    ) -> None:
        """Registro isolado recebe o Gerador, o global não muda."""
        gerador = GeradorFake()
        registro_de_teste: dict[str, Gerador] = {}

        registrar_gerador("Fake", gerador, registro=registro_de_teste)

        assert registro_de_teste == {"Fake": gerador}
        assert "Fake" not in GERADORES_REGISTRADOS


class TestErro:
    """Erro esperado."""

    def test_registrar_gerador_com_nome_duplicado_falha(
        self,
    ) -> None:
        """Nome já registrado levanta ValueError, sem sobrescrever."""
        gerador = GeradorFake()
        registro_de_teste: dict[str, Gerador] = {"Fake": gerador}

        with pytest.raises(ValueError, match="Fake"):
            registrar_gerador("Fake", GeradorFake(), registro=registro_de_teste)

        assert registro_de_teste == {"Fake": gerador}

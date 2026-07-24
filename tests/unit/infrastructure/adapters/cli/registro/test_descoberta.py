"""Testes de descobrir_extratores/descobrir_geradores/descobrir_plugins."""

from collections.abc import Iterable
from importlib.metadata import EntryPoint

from tests.unit.infrastructure.adapters.cli.registro.fixture_extrator_plugin import (
    REGISTRO_VALIDO as REGISTRO_EXTRATOR_VALIDO,
)
from tests.unit.infrastructure.adapters.cli.registro.fixture_gerador_plugin import (
    GeradorPluginFake,
)

from ddf.domain.ports.gerador import Gerador
from ddf.infrastructure.adapters.cli.registro.descoberta import (
    descobrir_extratores,
    descobrir_geradores,
)
from ddf.infrastructure.adapters.cli.registro.extratores import (
    EXTRATORES_REGISTRADOS,
    ExtratorRegistrado,
)
from ddf.infrastructure.adapters.cli.registro.geradores import GERADORES_REGISTRADOS

_MODULO_FIXTURE_EXTRATOR = (
    "tests.unit.infrastructure.adapters.cli.registro.fixture_extrator_plugin"
)
_MODULO_FIXTURE_GERADOR = (
    "tests.unit.infrastructure.adapters.cli.registro.fixture_gerador_plugin"
)


def _pontos(*entradas: EntryPoint) -> object:
    """Fábrica de `entry_points_fn` fake que devolve `entradas`, ignorando `group`."""

    def entry_points_fn(*, group: str) -> Iterable[EntryPoint]:
        return entradas

    return entry_points_fn


# Caminho feliz
def test_descobrir_extratores_registra_plugin_valido_em_registro_isolado() -> None:
    """Caminho feliz: entry point válido é descoberto e populado no registro isolado."""
    ponto = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_EXTRATOR}:REGISTRO_VALIDO",
        group="ddf.extratores",
    )
    registro_de_teste: dict[str, ExtratorRegistrado] = {}

    avisos = descobrir_extratores(
        entry_points_fn=_pontos(ponto), registro=registro_de_teste
    )

    assert avisos == []
    assert registro_de_teste == {"Fake": REGISTRO_EXTRATOR_VALIDO}
    assert "Fake" not in EXTRATORES_REGISTRADOS


def test_descobrir_geradores_registra_plugin_valido_em_registro_isolado() -> None:
    """Caminho feliz: entry point válido é descoberto e populado no registro isolado."""
    ponto = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_GERADOR}:GeradorPluginFake",
        group="ddf.geradores",
    )
    registro_de_teste: dict[str, Gerador] = {}

    avisos = descobrir_geradores(
        entry_points_fn=_pontos(ponto), registro=registro_de_teste
    )

    assert avisos == []
    assert list(registro_de_teste) == ["Fake"]
    assert isinstance(registro_de_teste["Fake"], GeradorPluginFake)
    assert "Fake" not in GERADORES_REGISTRADOS


# Erro esperado
def test_descobrir_extratores_isola_import_quebrado_e_classe_fora_do_protocol() -> None:
    """Erro esperado: import quebrado e classe fora do Protocol viram Aviso isolado."""
    ponto_quebrado = EntryPoint(
        name="Quebrado",
        value=f"{_MODULO_FIXTURE_EXTRATOR}_inexistente:Algo",
        group="ddf.extratores",
    )
    ponto_invalido = EntryPoint(
        name="Invalido",
        value=f"{_MODULO_FIXTURE_EXTRATOR}:REGISTRO_INVALIDO",
        group="ddf.extratores",
    )
    ponto_valido = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_EXTRATOR}:REGISTRO_VALIDO",
        group="ddf.extratores",
    )
    registro_de_teste: dict[str, ExtratorRegistrado] = {}

    avisos = descobrir_extratores(
        entry_points_fn=_pontos(ponto_quebrado, ponto_invalido, ponto_valido),
        registro=registro_de_teste,
    )

    assert len(avisos) == 2
    assert registro_de_teste == {"Fake": REGISTRO_EXTRATOR_VALIDO}


def test_descobrir_geradores_isola_import_quebrado_e_classe_fora_do_protocol() -> None:
    """Erro esperado: import quebrado e classe fora do Protocol viram Aviso isolado."""
    ponto_quebrado = EntryPoint(
        name="Quebrado",
        value=f"{_MODULO_FIXTURE_GERADOR}_inexistente:Algo",
        group="ddf.geradores",
    )
    ponto_invalido = EntryPoint(
        name="Invalido",
        value=f"{_MODULO_FIXTURE_GERADOR}:NaoSatisfazGerador",
        group="ddf.geradores",
    )
    ponto_valido = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_GERADOR}:GeradorPluginFake",
        group="ddf.geradores",
    )
    registro_de_teste: dict[str, Gerador] = {}

    avisos = descobrir_geradores(
        entry_points_fn=_pontos(ponto_quebrado, ponto_invalido, ponto_valido),
        registro=registro_de_teste,
    )

    assert len(avisos) == 2
    assert list(registro_de_teste) == ["Fake"]


# Caso de borda
def test_descobrir_extratores_com_nomes_duplicados_isola_colisao() -> None:
    """Borda: dois entry points com o mesmo nome — o segundo vira Aviso de colisão."""
    ponto_1 = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_EXTRATOR}:REGISTRO_VALIDO",
        group="ddf.extratores",
    )
    ponto_2 = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_EXTRATOR}:REGISTRO_VALIDO",
        group="ddf.extratores",
    )
    registro_de_teste: dict[str, ExtratorRegistrado] = {}

    avisos = descobrir_extratores(
        entry_points_fn=_pontos(ponto_1, ponto_2), registro=registro_de_teste
    )

    assert len(avisos) == 1
    assert "Fake" in avisos[0].mensagem
    assert registro_de_teste == {"Fake": REGISTRO_EXTRATOR_VALIDO}


def test_descobrir_geradores_com_nomes_duplicados_isola_colisao() -> None:
    """Borda: dois entry points com o mesmo nome — o segundo vira Aviso de colisão."""
    ponto_1 = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_GERADOR}:GeradorPluginFake",
        group="ddf.geradores",
    )
    ponto_2 = EntryPoint(
        name="Fake",
        value=f"{_MODULO_FIXTURE_GERADOR}:GeradorPluginFake",
        group="ddf.geradores",
    )
    registro_de_teste: dict[str, Gerador] = {}

    avisos = descobrir_geradores(
        entry_points_fn=_pontos(ponto_1, ponto_2), registro=registro_de_teste
    )

    assert len(avisos) == 1
    assert "Fake" in avisos[0].mensagem
    assert list(registro_de_teste) == ["Fake"]

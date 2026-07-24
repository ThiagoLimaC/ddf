"""Descoberta de Extratores/Geradores de terceiro via entry points.

Não inclui Analisador — ao contrário de Extrator/Gerador (escolhidos pelo
usuário em menus do wizard), todo Analisador registrado roda
incondicionalmente em toda execução, e Analisador é a ACL entre Curation e
Analysis.
"""

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points

from ddf.domain.ports.extrator import Extrator
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.aviso import Aviso
from ddf.infrastructure.adapters.cli.registro.extratores import registrar_extrator
from ddf.infrastructure.adapters.cli.registro.geradores import registrar_gerador

_ORIGEM = "descoberta-de-plugins"


def _descobrir(
    grupo: str,
    carregar_e_registrar: Callable[[EntryPoint], None],
    entry_points_fn: Callable[..., Iterable[EntryPoint]] = entry_points,
) -> list[Aviso]:
    """Itera os entry points de `grupo`, isolando falha por entrada como Aviso.

    Args:
        grupo: nome do grupo de entry points.
        carregar_e_registrar: função que carrega e registra uma única
            entrada; qualquer exceção que levantar vira Aviso, sem impedir
            o processamento das demais entradas.
        entry_points_fn: função que lista os entry points do grupo. Usa
            `importlib.metadata.entry_points` por padrão — parametrizado
            para permitir testar a descoberta sem instalar um pacote real.
    """
    avisos = []
    for ponto in entry_points_fn(group=grupo):
        try:
            carregar_e_registrar(ponto)
        except Exception as erro:
            avisos.append(
                Aviso(f"Plugin '{ponto.name}' ({grupo}) falhou: {erro}", origem=_ORIGEM)
            )
    return avisos


def descobrir_extratores(
    entry_points_fn: Callable[..., Iterable[EntryPoint]] = entry_points,
) -> list[Aviso]:
    """Descobre Extratores via entry points do grupo "ddf.extratores".

    Cada entry point deve apontar para uma instância de `ExtratorRegistrado`
    (classe + função de construção interativa) já montada pelo plugin.

    Args:
        entry_points_fn: ver `_descobrir`.
    """

    def carregar(ponto: EntryPoint) -> None:
        registrado = ponto.load()
        if not issubclass(registrado.classe_extrator, Extrator):
            raise TypeError(
                f"'{registrado.classe_extrator}' não satisfaz o Protocol Extrator"
            )
        registrar_extrator(ponto.name, registrado.classe_extrator, registrado.construir)

    return _descobrir("ddf.extratores", carregar, entry_points_fn)


def descobrir_geradores(
    entry_points_fn: Callable[..., Iterable[EntryPoint]] = entry_points,
) -> list[Aviso]:
    """Descobre Geradores via entry points do grupo "ddf.geradores".

    Cada entry point deve apontar para uma classe de Gerador com construtor
    sem argumentos.

    Args:
        entry_points_fn: ver `_descobrir`.
    """

    def carregar(ponto: EntryPoint) -> None:
        instancia = ponto.load()()
        if not isinstance(instancia, Gerador):
            raise TypeError(f"'{instancia}' não satisfaz o Protocol Gerador")
        registrar_gerador(ponto.name, instancia)

    return _descobrir("ddf.geradores", carregar, entry_points_fn)


def descobrir_plugins() -> list[Aviso]:
    """Descobre Extratores e Geradores de terceiro registrados via entry points."""
    return descobrir_extratores() + descobrir_geradores()

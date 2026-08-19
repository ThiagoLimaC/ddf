"""Descoberta dos entry points nativos de verdade, sem fake.

Diferente de `tests/unit/.../test_descoberta.py` (que injeta um
`entry_points_fn` fake para isolar a lógica de `_descobrir`), este teste
depende do pacote `ddf` estar instalado com o metadata real declarado em
`pyproject.toml` — por isso vive em `tests/integration/`, não em
`tests/unit/`. Ele existe para pegar em CI um erro de digitação num
caminho `"módulo:atributo"` do `pyproject.toml` (ex.: `_REGISTRO_POSTGRES`
sem o underscore), que quebraria só em runtime — nenhum `mypy`/`ruff`
pega esse tipo de erro, já que o valor é uma string opaca no TOML.
"""

from ddf.domain.ports.extrator import ExtratorRegistrado
from ddf.domain.ports.gerador import Gerador
from ddf.infrastructure.adapters.inbounds.cli.registro import descoberta


def test_entry_points_nativos_resolvem_sem_avisos() -> None:
    """Caminho feliz: os 5 adapters nativos são resolvidos via entry point real."""
    registro_extratores: dict[str, ExtratorRegistrado] = {}
    registro_geradores: dict[str, Gerador] = {}

    avisos_extratores = descoberta.descobrir_extratores(registro=registro_extratores)
    avisos_geradores = descoberta.descobrir_geradores(registro=registro_geradores)

    assert avisos_extratores == []
    assert avisos_geradores == []
    assert set(registro_extratores) == {"PostgreSQL", "MariaDB"}
    assert set(registro_geradores) == {"Markdown", "Dbt", "ContextoDeIA"}

"""Fixtures compartilhadas dos testes de cli/."""

from typing import Any

import pytest


@pytest.fixture
def interceptar_print(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Substitui `questionary.print`, registrando texto/estilo/terminador.

    `prompts.imprimir_destacado` (e tudo que passa por ela: `avisos.
    exibir_avisos`, mensagens de erro/sucesso coloridas em `cli/etapas/*.py`)
    escreve via `questionary.print` (`prompt_toolkit.print_formatted_text`),
    que não passa por `sys.stdout` de um jeito capturável por `capsys` —
    testar via monkeypatch direto no `questionary.print`, não via captura de
    saída do processo.
    """
    chamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "questionary.print",
        lambda texto, style=None, end="\n": chamadas.append(
            {"texto": texto, "style": style, "end": end}
        ),
    )
    return chamadas

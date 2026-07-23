"""Wizard end-to-end via CliRunner — só o Extrator é fake, o resto do pipeline é real.

Segue a convenção de `docs/engineer_guidelines.md`: testes de CLI injetam um
Extrator fake em `EXTRATORES_REGISTRADOS`, nunca mockam o driver de baixo
nível. Orquestrador, Sobrescrita (grava YAML real em `tmp_path`), Analisadores
e o GeradorMarkdown rodam de verdade.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import polars as pl
import pytest
from click.testing import CliRunner

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import extracao
from ddf.infrastructure.adapters.cli.registro.extratores import ExtratorRegistrado
from ddf.infrastructure.adapters.cli.wizard import executar


class ExtratorFake:
    """Extrator fake com um único escopo/tabela, estático, sem I/O real."""

    def listar_escopos(self) -> Resultado[list[str]]:
        """Devolve um único escopo fixo, 'public'."""
        return Sucesso(valor=["public"])

    def listar_tabelas(self, escopo: str) -> Resultado[list[tuple[str, str]]]:
        """Devolve uma única tabela fixa, 'public.clientes'."""
        return Sucesso(valor=[("public", "clientes")])

    def extrair_tabela(
        self, escopo: str, tabela: str
    ) -> Resultado[TabelaExtraida]:
        """Devolve uma TabelaExtraida fixa (id + nome, 3 linhas de amostra)."""
        return Sucesso(
            valor=TabelaExtraida(
                nome_tabela=tabela,
                nome_escopo=escopo,
                colunas=[
                    ColunaExtraida(
                        nome="id",
                        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
                        chave_primaria=True,
                    ),
                    ColunaExtraida(
                        nome="nome",
                        tipo_dado=TipoDeDado(
                            categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=100
                        ),
                    ),
                ],
                total_linhas=3,
                amostra=pl.DataFrame(
                    {"id": [1, 2, 3], "nome": ["ana", "bia", "caio"]}
                ),
                metadados_amostra=MetadadosDeAmostra(
                    estrategia="percentual_de_linhas", tamanho_amostra=3
                ),
            )
        )


def _fila_de_respostas(valores: list[object]) -> object:
    """Substitui uma função `questionary.*` por uma fila de respostas em ordem.

    Cada chamada da função original devolve um objeto com `.ask()`; aqui,
    cada `.ask()` consome o próximo valor da fila, na ordem em que as etapas
    do wizard perguntam.
    """
    fila = list(valores)

    class _Resposta:
        def ask(self) -> object:
            return fila.pop(0)

    def _fabrica(*args: object, **kwargs: object) -> _Resposta:
        return _Resposta()

    return _fabrica


@pytest.fixture(autouse=True)
def sem_ampulheta_no_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita a espera real de `ampulheta()` durante o teste end-to-end."""

    @contextmanager
    def _sem_animacao(mensagem: str) -> Generator[None, None, None]:
        yield

    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.ampulheta", _sem_animacao
    )


def test_wizard_fluxo_completo_com_extrator_fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Caminho feliz: as 14 etapas rodam de ponta a ponta e geram o Markdown."""
    diretorio_overrides = tmp_path / "overrides"
    destino = tmp_path / "artefatos"

    monkeypatch.setattr(
        extracao,
        "EXTRATORES_REGISTRADOS",
        {
            "Fake": ExtratorRegistrado(
                classe_extrator=ExtratorFake, construir=lambda cfg: ExtratorFake()
            )
        },
    )
    monkeypatch.setattr(
        "questionary.select",
        _fila_de_respostas(["Percentual de linhas", "Fake"]),
    )
    monkeypatch.setattr(
        "questionary.text",
        _fila_de_respostas(["10", str(diretorio_overrides), str(destino)]),
    )
    monkeypatch.setattr(
        "questionary.checkbox", _fila_de_respostas([["public"], ["Markdown"]])
    )
    monkeypatch.setattr("questionary.confirm", _fila_de_respostas([True]))
    monkeypatch.setattr(
        "questionary.press_any_key_to_continue", _fila_de_respostas([True])
    )

    resultado = CliRunner().invoke(executar)

    assert resultado.exit_code == 0, resultado.output
    assert (destino / "public" / "clientes.md").exists()
    assert (diretorio_overrides / "public" / "clientes.yaml").exists()

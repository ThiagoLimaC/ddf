"""Testes das etapas 12-14 do wizard: destino, confirmação e execução dos Geradores."""

from pathlib import Path

import pytest

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import geracao


class GeradorFake:
    """Gerador fake que devolve um Resultado pré-configurado quando chamado."""

    requer: list[object] = []

    def __init__(self, resultado: Resultado[None]) -> None:
        """Guarda o Resultado que __call__ sempre devolve."""
        self._resultado = resultado

    def __call__(
        self, entrada: BancoAnalisado, destino: Path
    ) -> Resultado[None]:
        """Devolve o Resultado configurado, ignorando os argumentos recebidos."""
        return self._resultado


# sugerir_destino() — caminho feliz


def test_sugerir_destino_com_um_gerador_usa_a_sugestao_especifica() -> None:
    """Caminho feliz: um único Gerador escolhido sugere seu destino específico."""
    assert geracao.sugerir_destino(["Dbt"]) == "artefatos/dbt"


# sugerir_destino() — borda


def test_sugerir_destino_com_varios_geradores_usa_destino_generico() -> None:
    """Borda: mais de um Gerador escolhido sugere o destino genérico."""
    assert geracao.sugerir_destino(["Markdown", "Dbt"]) == "artefatos"


def test_sugerir_destino_com_nome_camel_case_vira_snake_case() -> None:
    """Borda: nome de registro sem entrada cadastrada é convertido genericamente.

    Não há dicionário de exceções por nome — "ContextoDeIA" vira
    "contexto_de_ia" pela mesma regra usada para qualquer outro nome,
    Gerador nativo ou de plugin de terceiro.
    """
    assert geracao.sugerir_destino(["ContextoDeIA"]) == "artefatos/contexto_de_ia"
    assert geracao.sugerir_destino(["GeradorNovo"]) == "artefatos/gerador_novo"


# confirmar_execucao() — caminho feliz e erro esperado


def test_confirmar_execucao_aceita_e_nao_sai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Caminho feliz: confirmação aceita não interrompe o processo."""
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda mensagem: True
    )

    geracao.confirmar_execucao(["Markdown"], tmp_path)  # não deve levantar SystemExit


def test_confirmar_execucao_recusada_sai_com_codigo_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Erro esperado: usuário recusa a confirmação, sai com código 0."""
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda mensagem: False
    )

    with pytest.raises(SystemExit) as excinfo:
        geracao.confirmar_execucao(["Markdown"], tmp_path)

    assert excinfo.value.code == 0


# executar_geradores() — caminho feliz


def test_executar_geradores_com_sucesso_nao_sai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Caminho feliz: todos os Geradores escolhidos rodam com sucesso."""
    monkeypatch.setattr(
        geracao, "GERADORES_REGISTRADOS", {"Markdown": GeradorFake(Sucesso(valor=None))}
    )
    banco_analisado = BancoAnalisado(tabelas=[])

    geracao.executar_geradores(["Markdown"], banco_analisado, tmp_path)

    assert "'Markdown': artefato(s) escrito(s)" in capsys.readouterr().out


# executar_geradores() — erro esperado


def test_executar_geradores_com_falha_sai_com_codigo_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Erro esperado: Falha de um Gerador é reportada e sai com código 1."""
    monkeypatch.setattr(
        geracao,
        "GERADORES_REGISTRADOS",
        {"Dbt": GeradorFake(Falha(erro="permissão negada"))},
    )
    banco_analisado = BancoAnalisado(tabelas=[])

    with pytest.raises(SystemExit) as excinfo:
        geracao.executar_geradores(["Dbt"], banco_analisado, tmp_path)

    assert excinfo.value.code == 1
    assert "Falha em 'Dbt': permissão negada" in capsys.readouterr().out


# executar_geradores() — borda


def test_executar_geradores_continua_apos_uma_falha_isolada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Borda: falha de um Gerador não impede os demais de rodar."""
    monkeypatch.setattr(
        geracao,
        "GERADORES_REGISTRADOS",
        {
            "Dbt": GeradorFake(Falha(erro="permissão negada")),
            "Markdown": GeradorFake(Sucesso(valor=None)),
        },
    )
    banco_analisado = BancoAnalisado(tabelas=[])

    with pytest.raises(SystemExit):
        geracao.executar_geradores(["Dbt", "Markdown"], banco_analisado, tmp_path)

    saida = capsys.readouterr().out
    assert "Falha em 'Dbt'" in saida
    assert "'Markdown': artefato(s) escrito(s)" in saida

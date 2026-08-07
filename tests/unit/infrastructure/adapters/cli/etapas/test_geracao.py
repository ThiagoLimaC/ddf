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
        self.destino_recebido: Path | None = None

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Grava o destino recebido e devolve o Resultado configurado."""
        self.destino_recebido = destino
        return self._resultado


# confirmar_execucao() — caminho feliz e erro esperado


class TestFeliz:
    """Caminho feliz."""

    def test_confirmar_execucao_aceita_e_nao_sai(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """confirmação aceita não interrompe o processo."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda mensagem: True
        )

        geracao.confirmar_execucao(
            ["Markdown"], tmp_path
        )  # não deve levantar SystemExit

    def test_executar_geradores_com_sucesso_nao_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Todos os Geradores escolhidos rodam com sucesso."""
        gerador_fake = GeradorFake(Sucesso(valor=None))
        monkeypatch.setattr(
            geracao, "GERADORES_REGISTRADOS", {"Markdown": gerador_fake}
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        geracao.executar_geradores(["Markdown"], banco_analisado, tmp_path)

        assert "'Markdown': artefato escrito" in capsys.readouterr().out
        assert gerador_fake.destino_recebido == tmp_path / "markdown"

    def test_executar_geradores_escreve_cada_gerador_em_subpasta_propria(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Dois Geradores escolhidos na mesma execução não se misturam.

        Reprodução direta do bug da issue #77 — antes, `executar_geradores`
        passava o mesmo `destino` para todos os Geradores escolhidos.
        """
        gerador_markdown = GeradorFake(Sucesso(valor=None))
        gerador_dbt = GeradorFake(Sucesso(valor=None))
        monkeypatch.setattr(
            geracao,
            "GERADORES_REGISTRADOS",
            {"Markdown": gerador_markdown, "Dbt": gerador_dbt},
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        geracao.executar_geradores(["Markdown", "Dbt"], banco_analisado, tmp_path)

        assert gerador_markdown.destino_recebido == tmp_path / "markdown"
        assert gerador_dbt.destino_recebido == tmp_path / "dbt"
        assert gerador_markdown.destino_recebido != gerador_dbt.destino_recebido


class TestErro:
    """Erro esperado."""

    def test_confirmar_execucao_recusada_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """usuário recusa a confirmação, sai com código 0."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda mensagem: False
        )

        with pytest.raises(SystemExit) as excinfo:
            geracao.confirmar_execucao(["Markdown"], tmp_path)

        assert excinfo.value.code == 0

    def test_executar_geradores_com_falha_sai_com_codigo_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Falha de um Gerador é reportada e sai com código 1."""
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


class TestBorda:
    """Bordas."""

    def test_executar_geradores_continua_apos_uma_falha_isolada(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Falha de um Gerador não impede os demais de rodar."""
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
        assert "'Markdown': artefato escrito" in saida

    def test_executar_geradores_converte_nome_camel_case_em_slug_snake_case(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Nome de registro sem entrada cadastrada é convertido genericamente.

        Não há dicionário de exceções por nome — "ContextoDeIA" vira
        "contexto_de_ia" pela mesma regra usada para qualquer outro nome,
        Gerador nativo ou de plugin de terceiro.
        """
        gerador_fake = GeradorFake(Sucesso(valor=None))
        monkeypatch.setattr(
            geracao, "GERADORES_REGISTRADOS", {"ContextoDeIA": gerador_fake}
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        geracao.executar_geradores(["ContextoDeIA"], banco_analisado, tmp_path)

        assert gerador_fake.destino_recebido == tmp_path / "contexto_de_ia"

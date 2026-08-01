"""Testes das etapas 9-11 do wizard: escolha de Geradores, validação e análise."""

import pytest

from ddf.domain.model.analysis import (
    ContextoDeAnalise,
    MetricasBaseColuna,
    TipoDeMetrica,
)
from ddf.domain.model.curation import BancoCurado
from ddf.domain.shared.resultado import Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import analise


class AnalisadorFake:
    """Analisador fake que devolve o ContextoDeAnalise sem alterar nada."""

    produz: list[TipoDeMetrica] = []
    requer: list[TipoDeMetrica] = []

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
        """Devolve o próprio ContextoDeAnalise recebido, sem calcular métricas."""
        return Sucesso(valor=entrada)


class GeradorFake:
    """Gerador fake, usado só para popular ANALISADORES_REGISTRADOS/GERADORES."""

    requer: list[TipoDeMetrica] = []


# escolher_geradores() — caminho feliz


class TestFeliz:
    """Caminho feliz."""

    def test_escolher_geradores_devolve_a_escolha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Devolve os nomes de Gerador escolhidos pelo usuário."""
        monkeypatch.setattr(
            analise, "GERADORES_REGISTRADOS", {"Markdown": GeradorFake()}
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.escolher_multiplos",
            lambda mensagem, escolhas: ["Markdown"],
        )

        assert analise.escolher_geradores() == ["Markdown"]

    def test_validar_selecao_sem_dependencias_devolve_os_analisadores(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sem produz/requer, valida e devolve todos os Analisadores."""
        analisador = AnalisadorFake()
        monkeypatch.setattr(analise, "ANALISADORES_REGISTRADOS", {"Fake": analisador})
        monkeypatch.setattr(
            analise, "GERADORES_REGISTRADOS", {"Markdown": GeradorFake()}
        )

        ordenados = analise.validar_selecao(["Markdown"])

        assert ordenados == [analisador]

    def test_analisar_devolve_o_banco_analisado_vazio(
        self,
    ) -> None:
        """Roda o Analisador via compor() e devolve o BancoAnalisado."""
        banco_curado = BancoCurado(tabelas=[])

        banco_analisado = analise.analisar([AnalisadorFake()], banco_curado)

        assert banco_analisado.tabelas == []


class TestErro:
    """Erro esperado."""

    def test_validar_selecao_com_dependencia_ausente_sai_com_codigo_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Gerador exige uma métrica que nenhum Analisador produz."""

        class GeradorExigente:
            requer: list[TipoDeMetrica] = [MetricasBaseColuna]

        monkeypatch.setattr(analise, "ANALISADORES_REGISTRADOS", {})
        monkeypatch.setattr(
            analise, "GERADORES_REGISTRADOS", {"Exigente": GeradorExigente()}
        )

        with pytest.raises(SystemExit) as excinfo:
            analise.validar_selecao(["Exigente"])

        assert excinfo.value.code == 1

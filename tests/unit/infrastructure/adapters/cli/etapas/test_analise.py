"""Testes das etapas 9-11 do wizard: escolha de Geradores, validação e análise.

`pipeline.analise` é fakeado nos testes de `analisar` — verificam só
comportamento de UI (ordem de exibição de avisos, código de saída). O
núcleo (compor() sobre os Analisadores) é coberto em
`tests/unit/pipeline/test_analise.py`.
"""

from typing import Any

import pytest

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ContextoDeAnalise,
    MetricasBaseColuna,
    TipoDeMetrica,
)
from ddf.domain.model.curation import BancoCurado
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.cli.etapas import analise
from ddf.pipeline import analise as pipeline_analise


class AnalisadorFake:
    """Analisador fake usado só para popular ANALISADORES_REGISTRADOS."""

    produz: list[TipoDeMetrica] = []
    requer: list[TipoDeMetrica] = []

    def __call__(self, entrada: ContextoDeAnalise) -> Sucesso[ContextoDeAnalise]:
        """Não é exercitado por estes testes — pipeline.analise é fakeado."""
        return Sucesso(valor=entrada)


class GeradorFake:
    """Gerador fake usado só para popular GERADORES_REGISTRADOS."""

    requer: list[TipoDeMetrica] = []


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

    def test_analisar_devolve_o_banco_analisado_do_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Devolve o BancoAnalisado produzido por pipeline.analise.analisar."""
        banco_analisado = BancoAnalisado(tabelas=[])
        monkeypatch.setattr(
            pipeline_analise,
            "analisar",
            lambda analisadores, banco_curado: Sucesso(valor=banco_analisado),
        )

        resultado = analise.analisar([], BancoCurado(tabelas=[]))

        assert resultado is banco_analisado


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

    def test_analisar_com_falha_do_pipeline_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do pipeline sai com código 1."""
        monkeypatch.setattr(
            pipeline_analise,
            "analisar",
            lambda analisadores, banco_curado: Falha(erro="métrica não calculável"),
        )

        with pytest.raises(SystemExit) as excinfo:
            analise.analisar([], BancoCurado(tabelas=[]))

        assert excinfo.value.code == 1


class TestBorda:
    """Bordas."""

    def test_analisar_exibe_avisos_antes_da_mensagem_de_sucesso(
        self,
        monkeypatch: pytest.MonkeyPatch,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Avisos acumulados pelo pipeline aparecem antes de "✓ Análise concluída."."""
        resultado = Sucesso(
            valor=BancoAnalisado(tabelas=[]),
            avisos=[Aviso(mensagem="amostra pequena em 'public.clientes'", origem="X")],
        )
        monkeypatch.setattr(
            pipeline_analise, "analisar", lambda analisadores, banco_curado: resultado
        )

        analise.analisar([], BancoCurado(tabelas=[]))

        textos = [chamada["texto"] for chamada in interceptar_print]
        indice_aviso = next(
            i for i, texto in enumerate(textos) if "amostra pequena" in texto
        )
        indice_sucesso = next(
            i for i, texto in enumerate(textos) if "Análise concluída" in texto
        )
        assert indice_aviso < indice_sucesso

    def test_analisar_passa_um_analisador_que_e_protocol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uma instância real do Protocol Analisador chega intacta ao pipeline."""
        analisador: Analisador = AnalisadorFake()
        recebidos: list[list[Analisador]] = []

        def _fake(
            analisadores: list[Analisador], banco_curado: BancoCurado
        ) -> Sucesso[BancoAnalisado]:
            recebidos.append(analisadores)
            return Sucesso(valor=BancoAnalisado(tabelas=[]))

        monkeypatch.setattr(pipeline_analise, "analisar", _fake)

        analise.analisar([analisador], BancoCurado(tabelas=[]))

        assert recebidos == [[analisador]]

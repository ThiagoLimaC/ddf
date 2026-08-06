"""Testes das etapas 1-5 do wizard: conexão, escopos, amostragem e extração."""

from collections.abc import Callable

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import ExtratorRegistrado
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import extracao
from ddf.infrastructure.adapters.cli.registro.estrategias import EstrategiaRegistrada
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)


class ExtratorFake:
    """Extrator fake com respostas programadas por chamada, em fila."""

    def __init__(
        self,
        respostas_escopos: list[Resultado[list[str]]],
        respostas_tabelas: dict[str, Resultado[list[tuple[str, str]]]] | None = None,
    ) -> None:
        """Guarda as respostas programadas de listar_escopos()/listar_tabelas().

        Args:
            respostas_escopos: fila de Resultados devolvidos por chamadas
                sucessivas de listar_escopos() (uma por tentativa de conexão).
            respostas_tabelas: mapeia escopo -> Resultado de listar_tabelas().
        """
        self._respostas_escopos = list(respostas_escopos)
        self._respostas_tabelas = respostas_tabelas or {}

    def listar_escopos(self) -> Resultado[list[str]]:
        """Devolve a próxima resposta programada da fila."""
        return self._respostas_escopos.pop(0)

    def listar_tabelas(self, escopo: str) -> Resultado[list[tuple[str, str]]]:
        """Devolve a resposta programada para o escopo informado."""
        return self._respostas_tabelas[escopo]

    def extrair_tabela(self, escopo: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(self, resultado_extrair: Resultado[list[TabelaExtraida]]) -> None:
        """Guarda o Resultado que extrair() sempre devolve, independente dos args."""
        self._resultado_extrair = resultado_extrair

    def extrair(
        self,
        escopos: list[str],
        extrator: object,
        progresso: Callable[[str], None] | None = None,
        ao_conhecer_total: Callable[[int], None] | None = None,
        inicio: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Devolve o Resultado configurado, chamando ao_conhecer_total/inicio/progresso.

        Simula o comportamento real de OrquestradorParalelo: informa o total,
        depois "inicia" e "conclui" cada item da lista de sucesso configurada,
        nessa ordem.
        """
        tabelas = (
            self._resultado_extrair.valor
            if isinstance(self._resultado_extrair, Sucesso)
            else []
        )
        if ao_conhecer_total is not None:
            ao_conhecer_total(len(tabelas))
        for tabela in tabelas:
            identificador = f"{tabela.nome_escopo}.{tabela.nome_tabela}"
            if inicio is not None:
                inicio(identificador)
            if progresso is not None:
                progresso(identificador)
        return self._resultado_extrair

    def aplicar_sobrescritas(
        self,
        tabelas: object,
        sobrescrita: object,
        progresso: object = None,
        inicio: object = None,
    ) -> Resultado[object]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


# configurar_amostragem() — caminho feliz


class TestFeliz:
    """Caminho feliz."""

    def test_configurar_amostragem_usa_a_estrategia_escolhida(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Atribui a estratégia escolhida à configuração recebida."""
        registro = {
            "Percentual de linhas": EstrategiaRegistrada(
                construir=lambda: PercentualDeLinhas(percentual=10.0),
            )
        }
        monkeypatch.setattr(extracao, "ESTRATEGIAS_REGISTRADAS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.selecionar",
            lambda mensagem, escolhas: "Percentual de linhas",
        )
        configuracao = ConfiguracaoDeExtracao()

        extracao.configurar_amostragem(configuracao)

        assert isinstance(configuracao.estrategia, PercentualDeLinhas)

    def test_conectar_com_sucesso_na_primeira_tentativa(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Conecta e devolve escopos na 1ª tentativa, sem estratégia."""
        extrator_fake = ExtratorFake([Sucesso(valor=["public", "vendas"])])
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=type(extrator_fake), construir=lambda cfg: extrator_fake
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.selecionar", lambda *a: "Fake"
        )

        extrator, configuracao, escopos = extracao.conectar()

        assert extrator is extrator_fake
        assert configuracao.estrategia is None
        assert escopos == ["public", "vendas"]

    def test_extrair_devolve_as_tabelas_do_orquestrador(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Devolve as tabelas extraídas pelo orquestrador."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))
        extrator_fake = ExtratorFake(
            respostas_escopos=[], respostas_tabelas={"public": Sucesso(valor=[])}
        )

        tabelas = extracao.extrair(orquestrador, extrator_fake, ["public"])  # type: ignore[arg-type]

        assert tabelas == [tabela]


class TestErro:
    """Erro esperado."""

    def test_testar_conexao_esgota_tentativas_e_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """3 falhas seguidas de conexão saem com código 1, sem retry cego."""
        extrator_fake = ExtratorFake(
            [
                Falha(erro="senha incorreta"),
                Falha(erro="senha incorreta"),
                Falha(erro="senha incorreta"),
            ]
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.selecionar",
            lambda *a: "Tentar novamente",
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao(extrator_fake)  # type: ignore[arg-type]

        assert excinfo.value.code == 1

    def test_extrair_com_falha_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do orquestrador sai com código 1."""
        orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela extraída"))
        extrator_fake = ExtratorFake(
            respostas_escopos=[], respostas_tabelas={"public": Sucesso(valor=[])}
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao.extrair(orquestrador, extrator_fake, ["public"])  # type: ignore[arg-type]

        assert excinfo.value.code == 1


class TestBorda:
    """Bordas."""

    def test_testar_conexao_usuario_escolhe_sair_antes_do_limite(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """usuário escolhe 'Sair' após 1 falha, sem esperar as 3 tentativas."""
        extrator_fake = ExtratorFake([Falha(erro="conexão recusada")])
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.selecionar", lambda *a: "Sair"
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao(extrator_fake)  # type: ignore[arg-type]

        assert excinfo.value.code == 1

    def test_extrair_usa_total_do_orquestrador_na_barra_de_progresso(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Total exibido vem de ao_conhecer_total, sem listar tabelas por fora."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))
        extrator_fake = ExtratorFake(respostas_escopos=[], respostas_tabelas={})

        extracao.extrair(orquestrador, extrator_fake, ["public"])  # type: ignore[arg-type]

        assert "(1/1)" in capsys.readouterr().out

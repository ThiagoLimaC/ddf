"""Testes das etapas 1-5 do wizard: conexão, escopos, amostragem e extração."""

from collections.abc import Callable
from typing import Any

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import extracao
from ddf.infrastructure.adapters.cli.registro.estrategias import EstrategiaRegistrada
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.pipeline.estagio import Estagio


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

    def listar_tabelas(self, escopo: str, /) -> Resultado[list[tuple[str, str]]]:
        """Devolve a resposta programada para o escopo informado."""
        return self._respostas_tabelas[escopo]

    def extrair_tabela(
        self, escopo: str, tabela: str, /
    ) -> Resultado[TabelaExtraida]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(self, resultado_extrair: Resultado[list[TabelaExtraida]]) -> None:
        """Guarda o Resultado que extrair() sempre devolve, independente dos args."""
        self._resultado_extrair = resultado_extrair

    def extrair(
        self,
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Devolve o Resultado configurado, chamando progresso por item.

        Simula o comportamento real de OrquestradorParalelo, "processando"
        cada item da lista de sucesso configurada.
        """
        tabelas = (
            self._resultado_extrair.valor
            if isinstance(self._resultado_extrair, Sucesso)
            else []
        )
        if progresso is not None:
            for tabela in tabelas:
                progresso(f"{tabela.nome_escopo}.{tabela.nome_tabela}")
        return self._resultado_extrair

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
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
        extrator_fake = ExtratorFake(respostas_escopos=[])

        tabelas = extracao.extrair(
            orquestrador, extrator_fake, [("public", "clientes")]
        )

        assert tabelas == [tabela]

    def test_listar_pares_agrega_tabelas_de_multiplos_escopos(self) -> None:
        """Agrega as tabelas de todos os escopos informados, em pares."""
        extrator_fake = ExtratorFake(
            respostas_escopos=[],
            respostas_tabelas={
                "public": Sucesso(valor=[("public", "clientes")]),
                "vendas": Sucesso(
                    valor=[("vendas", "pedidos"), ("vendas", "itens")]
                ),
            },
        )

        pares = extracao.listar_pares(extrator_fake, ["public", "vendas"])

        assert pares == [
            ("public", "clientes"),
            ("vendas", "pedidos"),
            ("vendas", "itens"),
        ]

    def test_escolher_tabelas_recusando_restringir_devolve_todas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resposta padrão (não restringir) devolve os pares disponíveis intactos."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a, **k: False
        )
        pares_disponiveis = [("public", "clientes"), ("vendas", "pedidos")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == pares_disponiveis

    def test_escolher_tabelas_restringindo_devolve_apenas_o_subconjunto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restringindo, devolve só os pares cujo rótulo foi escolhido."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a, **k: True
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.escolher_multiplos",
            lambda *a, **k: ["vendas › pedidos"],
        )
        pares_disponiveis = [("public", "clientes"), ("vendas", "pedidos")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == [("vendas", "pedidos")]


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
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=type(extrator_fake), construir=lambda cfg: extrator_fake
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a: True
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao("Fake", ConfiguracaoDeExtracao())

        assert excinfo.value.code == 1

    def test_extrair_com_falha_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do orquestrador sai com código 1."""
        orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela extraída"))
        extrator_fake = ExtratorFake(respostas_escopos=[])

        with pytest.raises(SystemExit) as excinfo:
            extracao.extrair(
                orquestrador, extrator_fake, [("public", "clientes")]
            )

        assert excinfo.value.code == 1

    def test_listar_pares_escopo_com_falha_de_listagem_vira_aviso(
        self, interceptar_print: list[dict[str, Any]]
    ) -> None:
        """Escopo que falha ao listar vira Aviso, não impede os demais."""
        extrator_fake = ExtratorFake(
            respostas_escopos=[],
            respostas_tabelas={
                "public": Sucesso(valor=[("public", "clientes")]),
                "financeiro_typo": Falha("Escopo 'financeiro_typo' não encontrado."),
            },
        )

        pares = extracao.listar_pares(
            extrator_fake, ["public", "financeiro_typo"]
        )

        assert pares == [("public", "clientes")]
        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("financeiro_typo" in texto for texto in textos)
        assert any(
            "Escopo 'financeiro_typo' não encontrado." in texto for texto in textos
        )


class TestBorda:
    """Bordas."""

    def test_testar_conexao_reconstroi_extrator_a_cada_tentativa(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Falha não reusa a mesma credencial — reconstrói o Extrator no retry."""
        extrator_falho = ExtratorFake([Falha(erro="senha incorreta")])
        extrator_certo = ExtratorFake([Sucesso(valor=["public"])])
        respostas_construir = iter([extrator_falho, extrator_certo])
        monkeypatch.setattr(
            extracao,
            "EXTRATORES_REGISTRADOS",
            {
                "Fake": ExtratorRegistrado(
                    classe_extrator=ExtratorFake,
                    construir=lambda cfg: next(respostas_construir),
                )
            },
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a: True
        )

        extrator, escopos = extracao._testar_conexao(
            "Fake", ConfiguracaoDeExtracao()
        )

        assert extrator is extrator_certo
        assert escopos == ["public"]

    def test_testar_conexao_usuario_recusa_tentar_novamente_antes_do_limite(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """usuário recusa tentar de novo após 1 falha, sem esperar as 3 tentativas."""
        extrator_fake = ExtratorFake([Falha(erro="conexão recusada")])
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=type(extrator_fake), construir=lambda cfg: extrator_fake
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a: False
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao("Fake", ConfiguracaoDeExtracao())

        assert excinfo.value.code == 1

    def test_extrair_usa_o_total_de_pares_na_barra_de_progresso(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Total exibido vem de len(pares), já conhecido antes de chamar extrair."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))
        extrator_fake = ExtratorFake(respostas_escopos=[])

        extracao.extrair(
            orquestrador, extrator_fake, [("public", "clientes")]
        )

        assert "(1/1)" in capsys.readouterr().out

    def test_escolher_tabelas_selecao_vazia_repergunta_ate_marcar_algo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Seleção vazia não sai do wizard — repergunta até marcar ao menos uma."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.confirmar", lambda *a, **k: True
        )
        respostas = iter([[], ["public › clientes"]])
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.escolher_multiplos",
            lambda *a, **k: next(respostas),
        )
        pares_disponiveis = [("public", "clientes")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == [("public", "clientes")]

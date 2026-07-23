"""Testes das etapas 1-5 do wizard: amostragem, conexão, escopos e extração."""

from collections.abc import Callable

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import extracao
from ddf.infrastructure.adapters.cli.registro.estrategias import EstrategiaRegistrada
from ddf.infrastructure.adapters.cli.registro.extratores import ExtratorRegistrado
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
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

    def extrair_tabela(
        self, escopo: str, tabela: str
    ) -> Resultado[TabelaExtraida]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(self, resultado_extrair: Resultado[list[TabelaExtraida]]) -> None:
        """Guarda o Resultado que extrair() sempre devolve, independente dos args."""
        self._resultado_extrair = resultado_extrair

    def extrair(
        self, escopos: list[str], extrator: object, progresso: object = None
    ) -> Resultado[list[TabelaExtraida]]:
        """Devolve o Resultado configurado, ignorando os argumentos."""
        return self._resultado_extrair

    def aplicar_sobrescritas(
        self, tabelas: object, sobrescrita: object, progresso: object = None
    ) -> Resultado[object]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


# configurar_amostragem() — caminho feliz


def test_configurar_amostragem_usa_a_estrategia_escolhida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: monta a ConfiguracaoDeExtracao com a estratégia escolhida."""
    registro = {
        "Percentual de linhas": EstrategiaRegistrada(
            classe_estrategia=PercentualDeLinhas,
            construir=lambda: PercentualDeLinhas(percentual=10.0),
        )
    }
    monkeypatch.setattr(extracao, "ESTRATEGIAS_REGISTRADAS", registro)
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.selecionar",
        lambda mensagem, escolhas: "Percentual de linhas",
    )

    configuracao = extracao.configurar_amostragem()

    assert isinstance(configuracao, ConfiguracaoDeExtracao)
    assert isinstance(configuracao.estrategia, PercentualDeLinhas)


# conectar() / _testar_conexao() — caminho feliz


def test_conectar_com_sucesso_na_primeira_tentativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: conecta e devolve os escopos já na 1ª tentativa."""
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
    configuracao = ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=10))

    extrator, escopos = extracao.conectar(configuracao)

    assert extrator is extrator_fake
    assert escopos == ["public", "vendas"]


# _testar_conexao() — erro esperado (esgota tentativas e sai)


def test_testar_conexao_esgota_tentativas_e_sai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erro esperado: 3 falhas seguidas de conexão saem com código 1, sem retry cego."""
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


# _testar_conexao() — borda (usuário escolhe sair antes de esgotar tentativas)


def test_testar_conexao_usuario_escolhe_sair_antes_do_limite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borda: usuário escolhe 'Sair' após 1 falha, sem esperar as 3 tentativas."""
    extrator_fake = ExtratorFake([Falha(erro="conexão recusada")])
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.cli.prompts.selecionar", lambda *a: "Sair"
    )

    with pytest.raises(SystemExit) as excinfo:
        extracao._testar_conexao(extrator_fake)  # type: ignore[arg-type]

    assert excinfo.value.code == 1


# _contar_tabelas() — caminho feliz e borda


def test_contar_tabelas_soma_todos_os_escopos() -> None:
    """Caminho feliz: soma o total de tabelas de todos os escopos informados."""
    extrator_fake = ExtratorFake(
        respostas_escopos=[],
        respostas_tabelas={
            "public": Sucesso(valor=[("public", "clientes"), ("public", "pedidos")]),
            "vendas": Sucesso(valor=[("vendas", "itens")]),
        },
    )

    total = extracao._contar_tabelas(extrator_fake, ["public", "vendas"])  # type: ignore[arg-type]

    assert total == 3


def test_contar_tabelas_degrada_para_none_se_algum_escopo_falhar() -> None:
    """Borda: falha ao listar um escopo degrada para None, sem propagar erro aqui."""
    extrator_fake = ExtratorFake(
        respostas_escopos=[],
        respostas_tabelas={"public": Falha(erro="schema não encontrado")},
    )

    total = extracao._contar_tabelas(extrator_fake, ["public"])  # type: ignore[arg-type]

    assert total is None


# extrair() — caminho feliz


def test_extrair_devolve_as_tabelas_do_orquestrador(
    monkeypatch: pytest.MonkeyPatch,
    fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
) -> None:
    """Caminho feliz: devolve as tabelas extraídas pelo orquestrador."""
    tabela = fabrica_tabela_extraida("public", "clientes")
    orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))
    extrator_fake = ExtratorFake(
        respostas_escopos=[], respostas_tabelas={"public": Sucesso(valor=[])}
    )

    tabelas = extracao.extrair(orquestrador, extrator_fake, ["public"])  # type: ignore[arg-type]

    assert tabelas == [tabela]


# extrair() — erro esperado


def test_extrair_com_falha_sai_com_codigo_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: Falha do orquestrador sai com código 1."""
    orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela extraída"))
    extrator_fake = ExtratorFake(
        respostas_escopos=[], respostas_tabelas={"public": Sucesso(valor=[])}
    )

    with pytest.raises(SystemExit) as excinfo:
        extracao.extrair(orquestrador, extrator_fake, ["public"])  # type: ignore[arg-type]

    assert excinfo.value.code == 1

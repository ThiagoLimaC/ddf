"""Testes de registrar_estrategia e dos construtores privados de estratégia."""

import pytest

from ddf.domain.model.common.requisicao_de_amostragem import AmostragemProbabilistica
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.cli.registro.estrategias import (
    ESTRATEGIAS_REGISTRADAS,
    EstrategiaRegistrada,
    _construir_amostragem_por_faixa,
    _construir_percentual_de_linhas,
    registrar_estrategia,
)
from ddf.infrastructure.adapters.extractors.estrategias.amostragem_por_faixa import (
    AmostragemPorFaixa,
)
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)


class _RespostaFake:
    """Substitui o objeto que `questionary.text(...)` devolve."""

    def __init__(self, valor: object) -> None:
        self.valor = valor

    def __call__(self, *args: object, **kwargs: object) -> "_RespostaFake":
        return self

    def ask(self) -> object:
        """Devolve o valor pré-configurado, como `.ask()` do questionary faria."""
        return self.valor


class EstrategiaFake:
    """Estratégia fake usada só para popular o registro nos testes."""

    @property
    def nome(self) -> str:
        """Não é exercitado por registrar_estrategia — não precisa de corpo real."""
        return "fake"

    @property
    def requisicao(self) -> AmostragemProbabilistica:
        """Não é exercitado por registrar_estrategia — não precisa de corpo real."""
        return AmostragemProbabilistica(percentual=10.0)


def _construir_fake() -> EstrategiaDeAmostragem:
    """Construtor fake usado só para popular o registro nos testes."""
    return EstrategiaFake()


class TestFeliz:
    """Caminho feliz."""

    def test_registrar_estrategia_em_registro_isolado_nao_afeta_o_global(
        self,
    ) -> None:
        """Registro isolado recebe a estratégia, o global não muda."""
        registro_de_teste: dict[str, EstrategiaRegistrada] = {}

        registrar_estrategia("Fake", _construir_fake, registro=registro_de_teste)

        assert registro_de_teste == {
            "Fake": EstrategiaRegistrada(construir=_construir_fake)
        }
        assert "Fake" not in ESTRATEGIAS_REGISTRADAS

    def test_amostragem_por_faixa_com_percentual_e_seed_monta_estrategia(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Percentual/seed preenchidos montam a estratégia, sem pergunta de confirmação.

        Não confirma mais com sim/não (#116) — só as perguntas de valor.
        """
        respostas = iter(["5", "42"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        estrategia = _construir_amostragem_por_faixa()

        assert isinstance(estrategia, AmostragemPorFaixa)
        assert estrategia.requisicao.percentual == 5.0
        assert estrategia.requisicao.seed == 42

    def test_amostragem_por_faixa_com_percentual_fora_de_faixa_repete_ate_valido(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Percentual > 100 (ValidationError) repergunta até um percentual válido."""
        respostas = iter(["150", "", "5", "42"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )
        monkeypatch.setattr(
            "questionary.confirm", lambda *args, **kwargs: _RespostaFake(True)
        )

        estrategia = _construir_amostragem_por_faixa()

        assert isinstance(estrategia, AmostragemPorFaixa)
        assert estrategia.requisicao.percentual == 5.0
        assert estrategia.requisicao.seed == 42


class TestErro:
    """Erro esperado."""

    def test_amostragem_por_faixa_com_percentual_fora_de_faixa_recusa_repetir_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Percentual > 100 (ValidationError) pergunta se quer repetir; recusa, sai."""
        respostas = iter(["150", ""])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )
        monkeypatch.setattr(
            "questionary.confirm", lambda *args, **kwargs: _RespostaFake(False)
        )

        with pytest.raises(SystemExit) as excecao:
            _construir_amostragem_por_faixa()

        assert excecao.value.code == 0

    def test_registrar_estrategia_com_nome_duplicado_falha(
        self,
    ) -> None:
        """Nome já registrado levanta ValueError, sem sobrescrever."""
        registro_de_teste: dict[str, EstrategiaRegistrada] = {
            "Fake": EstrategiaRegistrada(construir=_construir_fake)
        }

        with pytest.raises(ValueError, match="Fake"):
            registrar_estrategia("Fake", _construir_fake, registro=registro_de_teste)

        assert registro_de_teste == {
            "Fake": EstrategiaRegistrada(construir=_construir_fake)
        }

    def test_construir_percentual_de_linhas_com_entrada_invalida_reprompt(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Percentual não numérico não crasha, reprompt até funcionar."""
        respostas = iter(["abc", "10", ""])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        estrategia = _construir_percentual_de_linhas()

        assert isinstance(estrategia, PercentualDeLinhas)
        assert estrategia.requisicao.percentual == 10.0
        assert estrategia.requisicao.seed is None


class TestBorda:
    """Bordas."""

    def test_construir_percentual_de_linhas_com_seed_devolve_seed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Seed preenchida (não em branco) é convertida e repassada."""
        respostas = iter(["5", "42"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        estrategia = _construir_percentual_de_linhas()

        assert isinstance(estrategia, PercentualDeLinhas)
        assert estrategia.requisicao.seed == 42

"""Testes de registrar_extrator e dos construtores privados de Extrator."""

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.infrastructure.adapters.cli.registro.extratores import (
    EXTRATORES_REGISTRADOS,
    _construir_extrator_mariadb,
    registrar_extrator,
)
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)


class _RespostaFake:
    """Substitui o objeto que `questionary.text/password(...)` devolve."""

    def __init__(self, valor: object) -> None:
        self.valor = valor

    def __call__(self, *args: object, **kwargs: object) -> "_RespostaFake":
        return self

    def ask(self) -> object:
        """Devolve o valor pré-configurado, como `.ask()` do questionary faria."""
        return self.valor


class ExtratorFake:
    """Extrator fake usado só para popular o registro nos testes."""

    def listar_escopos(self) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...

    def listar_tabelas(self, escopo: str) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...

    def extrair_tabela(self, escopo: str, tabela: str) -> object:
        """Não é exercitado por registrar_extrator — não precisa de corpo real."""
        ...


def _construir_fake(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Construtor fake usado só para popular o registro nos testes."""
    return ExtratorFake()


# Caminho feliz
def test_registrar_extrator_em_registro_isolado_nao_afeta_o_global() -> None:
    """Caminho feliz: registro isolado recebe o Extrator, o global não muda."""
    registro_de_teste: dict[str, ExtratorRegistrado] = {}

    registrar_extrator(
        "Fake", ExtratorFake, _construir_fake, registro=registro_de_teste
    )

    assert registro_de_teste == {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }
    assert "Fake" not in EXTRATORES_REGISTRADOS


# Erro esperado
def test_registrar_extrator_com_nome_duplicado_falha() -> None:
    """Erro esperado: nome já registrado levanta ValueError, sem sobrescrever."""
    registro_de_teste: dict[str, ExtratorRegistrado] = {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }

    with pytest.raises(ValueError, match="Fake"):
        registrar_extrator(
            "Fake", ExtratorFake, _construir_fake, registro=registro_de_teste
        )

    assert registro_de_teste == {
        "Fake": ExtratorRegistrado(
            classe_extrator=ExtratorFake, construir=_construir_fake
        )
    }


# _construir_extrator_mariadb() — erro esperado
def test_construir_extrator_mariadb_com_porta_invalida_reprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erro esperado: porta não numérica não crasha, reprompt até funcionar."""
    respostas_texto = iter(["host1", "abc", "3307", "user1"])
    monkeypatch.setattr(
        "questionary.text",
        lambda *args, **kwargs: _RespostaFake(next(respostas_texto)),
    )
    monkeypatch.setattr(
        "questionary.password", lambda *args, **kwargs: _RespostaFake("senha1")
    )
    configuracao = ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=10))

    extrator = _construir_extrator_mariadb(configuracao)

    assert isinstance(extrator, ExtratorMariaDB)

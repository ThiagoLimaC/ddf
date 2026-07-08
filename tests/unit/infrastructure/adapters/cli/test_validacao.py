"""Testes de validar_dependencias."""

from dataclasses import dataclass, field
from pathlib import Path

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ContextoDeAnalise,
    MetricaDeColuna,
    TipoDeMetrica,
)
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.validacao import validar_dependencias


class MetricaX(MetricaDeColuna):
    """Métrica fake usada só para montar grafos de dependência nos testes."""

    origem: str = "fake"


class MetricaY(MetricaDeColuna):
    """Métrica fake usada só para montar grafos de dependência nos testes."""

    origem: str = "fake"


class MetricaZ(MetricaDeColuna):
    """Métrica fake usada só para montar grafos de dependência nos testes."""

    origem: str = "fake"


@dataclass
class AnalisadorFake:
    """Analisador fake com produz/requer configuráveis, sem lógica real."""

    nome: str
    produz: list[TipoDeMetrica] = field(default_factory=list)
    requer: list[TipoDeMetrica] = field(default_factory=list)

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
        """Não é exercitado por validar_dependencias — não precisa de corpo real."""
        return Sucesso(valor=entrada)


@dataclass
class GeradorFake:
    """Gerador fake com requer configurável, sem lógica real."""

    nome: str
    requer: list[TipoDeMetrica] = field(default_factory=list)

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]:
        """Não é exercitado por validar_dependencias — não precisa de corpo real."""
        return Sucesso(valor=None)


# Caminho feliz
def test_analisador_e_gerador_com_dependencias_satisfeitas() -> None:
    """Caminho feliz: Gerador cujo requer é produzido pelo Analisador selecionado."""
    coluna = AnalisadorFake("Coluna", produz=[MetricaX], requer=[])
    gerador = GeradorFake("Markdown", requer=[MetricaX])

    resultado = validar_dependencias([coluna], [gerador])

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == [coluna]


def test_analisadores_fora_de_ordem_sao_reordenados() -> None:
    """Caminho feliz: Tabela antes de Coluna na entrada, mas Tabela depende dela."""
    coluna = AnalisadorFake("Coluna", produz=[MetricaX], requer=[])
    tabela = AnalisadorFake("Tabela", produz=[MetricaY], requer=[MetricaX])

    resultado = validar_dependencias([tabela, coluna], [])

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == [coluna, tabela]


def test_cadeia_transitiva_de_tres_analisadores_embaralhada() -> None:
    """Caminho feliz: C depende de B, B depende de A — resolve em cascata."""
    a = AnalisadorFake("A", produz=[MetricaX], requer=[])
    b = AnalisadorFake("B", produz=[MetricaY], requer=[MetricaX])
    c = AnalisadorFake("C", produz=[MetricaZ], requer=[MetricaY])

    resultado = validar_dependencias([c, a, b], [])

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == [a, b, c]

# Erro esperado
def test_gerador_com_dependencia_nao_produzida_falha() -> None:
    """Erro esperado: Gerador requer métrica que ninguém selecionado produz."""
    gerador = GeradorFake("Markdown", requer=[MetricaX])

    resultado = validar_dependencias([], [gerador])

    # A mensagem cita a classe (type(gerador).__name__), não o campo `nome` do
    # Fake — com Geradores reais cada um tem sua própria classe e o nome bate.
    assert isinstance(resultado, Falha)
    assert "GeradorFake" in resultado.erro
    assert "MetricaX" in resultado.erro


def test_analisador_com_dependencia_nao_produzida_falha() -> None:
    """Erro esperado: Analisador requer métrica que ninguém selecionado produz."""
    tabela = AnalisadorFake("Tabela", produz=[MetricaY], requer=[MetricaX])

    resultado = validar_dependencias([tabela], [])

    assert isinstance(resultado, Falha)
    assert "AnalisadorFake" in resultado.erro
    assert "MetricaX" in resultado.erro

# Borda
def test_listas_vazias_retornam_sucesso_vazio() -> None:
    """Borda: sem Analisadores nem Geradores selecionados — nada para validar."""
    resultado = validar_dependencias([], [])

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == []

def test_ciclo_entre_dois_analisadores_falha() -> None:
    """Borda: A requer o que só B produz, e B requer o que só A produz."""
    a = AnalisadorFake("A", produz=[MetricaX], requer=[MetricaY])
    b = AnalisadorFake("B", produz=[MetricaY], requer=[MetricaX])

    resultado = validar_dependencias([a, b], [])

    # Os dois entram na mensagem de ciclo — via type().__name__, ambos são
    # "AnalisadorFake" (mesma classe Fake).
    assert isinstance(resultado, Falha)
    assert "Ciclo" in resultado.erro
    assert resultado.erro.count("AnalisadorFake") == 2


def test_analisador_que_requer_a_propria_metrica_que_produz_falha_por_ciclo() -> None:
    """Borda: auto-dependência — Analisador requer o que ele mesmo produz."""
    autodependente = AnalisadorFake(
        "Autodependente", produz=[MetricaX], requer=[MetricaX]
    )

    resultado = validar_dependencias([autodependente], [])

    assert isinstance(resultado, Falha)
    assert "Ciclo" in resultado.erro


def test_dois_analisadores_produzindo_a_mesma_metrica_nao_falha() -> None:
    """Borda: dois Analisadores produzem a mesma métrica — último processado vence.

    Não há Analisador real hoje que duplique `produz`.
    """
    primeiro = AnalisadorFake("Primeiro", produz=[MetricaX], requer=[])
    segundo = AnalisadorFake("Segundo", produz=[MetricaX], requer=[])
    gerador = GeradorFake("Markdown", requer=[MetricaX])

    resultado = validar_dependencias([primeiro, segundo], [gerador])

    assert isinstance(resultado, Sucesso)
    assert {a.nome for a in resultado.valor} == {"Primeiro", "Segundo"}

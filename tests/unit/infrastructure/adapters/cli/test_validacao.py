"""Testes de validar_dependencias."""

from dataclasses import dataclass, field
from pathlib import Path

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ContextoDeAnalise,
    MetricaDeColuna,
    TipoDeMetrica,
)
from ddf.domain.ports.analisador import Analisador
from ddf.domain.ports.gerador import Gerador
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


def _analisadores(*fakes: AnalisadorFake) -> dict[str, Analisador]:
    """Monta o dict nome -> instância que validar_dependencias espera."""
    return {fake.nome: fake for fake in fakes}


def _geradores(*fakes: GeradorFake) -> dict[str, Gerador]:
    """Monta o dict nome -> instância que validar_dependencias espera."""
    return {fake.nome: fake for fake in fakes}


class TestFeliz:
    """Caminho feliz."""

    def test_analisador_e_gerador_com_dependencias_satisfeitas(
        self,
    ) -> None:
        """Gerador cujo requer é produzido pelo Analisador selecionado."""
        coluna = AnalisadorFake("Coluna", produz=[MetricaX], requer=[])
        gerador = GeradorFake("Markdown", requer=[MetricaX])

        resultado = validar_dependencias(_analisadores(coluna), _geradores(gerador))

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == [coluna]

    def test_analisadores_fora_de_ordem_sao_reordenados(
        self,
    ) -> None:
        """Tabela antes de Coluna na entrada, mas Tabela depende dela."""
        coluna = AnalisadorFake("Coluna", produz=[MetricaX], requer=[])
        tabela = AnalisadorFake("Tabela", produz=[MetricaY], requer=[MetricaX])

        resultado = validar_dependencias(_analisadores(tabela, coluna), _geradores())

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == [coluna, tabela]

    def test_cadeia_transitiva_de_tres_analisadores_embaralhada(
        self,
    ) -> None:
        """C depende de B, B depende de A — resolve em cascata."""
        a = AnalisadorFake("A", produz=[MetricaX], requer=[])
        b = AnalisadorFake("B", produz=[MetricaY], requer=[MetricaX])
        c = AnalisadorFake("C", produz=[MetricaZ], requer=[MetricaY])

        resultado = validar_dependencias(_analisadores(c, a, b), _geradores())

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == [a, b, c]


class TestErro:
    """Erro esperado."""

    def test_gerador_com_dependencia_nao_produzida_falha(
        self,
    ) -> None:
        """Gerador requer métrica que ninguém selecionado produz."""
        gerador = GeradorFake("Markdown", requer=[MetricaX])

        resultado = validar_dependencias(_analisadores(), _geradores(gerador))

        # A mensagem cita o rótulo de registro ("Markdown"), não o nome da
        # classe Python (GeradorFake) — é isso que o usuário vê no menu.
        assert isinstance(resultado, Falha)
        assert "Markdown" in resultado.erro
        assert "MetricaX" in resultado.erro

    def test_analisador_com_dependencia_nao_produzida_falha(
        self,
    ) -> None:
        """Analisador requer métrica que ninguém selecionado produz."""
        tabela = AnalisadorFake("Tabela", produz=[MetricaY], requer=[MetricaX])

        resultado = validar_dependencias(_analisadores(tabela), _geradores())

        assert isinstance(resultado, Falha)
        assert "Tabela" in resultado.erro
        assert "MetricaX" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_listas_vazias_retornam_sucesso_vazio(
        self,
    ) -> None:
        """Sem Analisadores nem Geradores selecionados — nada para validar."""
        resultado = validar_dependencias(_analisadores(), _geradores())

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == []

    def test_ciclo_entre_dois_analisadores_falha(
        self,
    ) -> None:
        """A requer o que só B produz, e B requer o que só A produz."""
        a = AnalisadorFake("A", produz=[MetricaX], requer=[MetricaY])
        b = AnalisadorFake("B", produz=[MetricaY], requer=[MetricaX])

        resultado = validar_dependencias(_analisadores(a, b), _geradores())

        # Os dois entram na mensagem de ciclo pelo rótulo de registro.
        assert isinstance(resultado, Falha)
        assert "Ciclo" in resultado.erro
        assert "A" in resultado.erro
        assert "B" in resultado.erro

    def test_analisador_que_requer_a_propria_metrica_que_produz_falha_por_ciclo(
        self,
    ) -> None:
        """auto-dependência — Analisador requer o que ele mesmo produz."""
        autodependente = AnalisadorFake(
            "Autodependente", produz=[MetricaX], requer=[MetricaX]
        )

        resultado = validar_dependencias(_analisadores(autodependente), _geradores())

        assert isinstance(resultado, Falha)
        assert "Ciclo" in resultado.erro
        assert "Autodependente" in resultado.erro

    def test_dois_analisadores_produzindo_a_mesma_metrica_nao_falha(
        self,
    ) -> None:
        """Dois Analisadores produzem a mesma métrica — último processado vence.

        Não há Analisador real hoje que duplique `produz`.
        """
        primeiro = AnalisadorFake("Primeiro", produz=[MetricaX], requer=[])
        segundo = AnalisadorFake("Segundo", produz=[MetricaX], requer=[])
        gerador = GeradorFake("Markdown", requer=[MetricaX])

        resultado = validar_dependencias(
            _analisadores(primeiro, segundo), _geradores(gerador)
        )

        assert isinstance(resultado, Sucesso)
        nomes: set[str] = set()
        for analisador in resultado.valor:
            assert isinstance(analisador, AnalisadorFake)
            nomes.add(analisador.nome)
        assert nomes == {"Primeiro", "Segundo"}

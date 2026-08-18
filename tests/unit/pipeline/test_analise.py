"""Testes do núcleo de composição da etapa de análise (sem UI)."""

from collections.abc import Callable
from dataclasses import dataclass, field

from ddf.domain.model.analysis import ContextoDeAnalise, MetricaDeColuna, TipoDeMetrica
from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline import analise


class MetricaFake(MetricaDeColuna):
    """Métrica fake usada só para exercitar produz/requer nos testes."""

    origem: str = "fake"


@dataclass
class AnalisadorFake:
    """Analisador fake com resultado configurável, sem cálculo de métrica real."""

    produz: list[TipoDeMetrica] = field(default_factory=list)
    requer: list[TipoDeMetrica] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)
    falha: str | None = None

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
        """Devolve Falha se configurado, senão repassa a entrada intacta."""
        if self.falha is not None:
            return Falha(erro=self.falha, avisos=self.avisos)
        return Sucesso(valor=entrada, avisos=self.avisos)


def _banco_curado(
    fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
) -> BancoCurado:
    tabela = fabrica_tabela_extraida("public", "clientes")
    return BancoCurado(tabelas=[fabrica_tabela_curada(tabela)])


class TestFeliz:
    """Caminho feliz."""

    def test_analisar_sem_analisadores_devolve_banco_analisado_vazio_de_metricas(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Lista vazia de Analisadores ainda monta o BancoAnalisado do curado."""
        banco_curado = _banco_curado(fabrica_tabela_extraida, fabrica_tabela_curada)

        resultado = analise.analisar([], banco_curado)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.valor.tabelas) == 1
        assert resultado.valor.tabelas[0].nome_tabela == "clientes"

    def test_analisar_acumula_avisos_de_todos_os_analisadores(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Avisos de cada Analisador chegam intactos no Sucesso final."""
        banco_curado = _banco_curado(fabrica_tabela_extraida, fabrica_tabela_curada)
        analisador = AnalisadorFake(
            produz=[MetricaFake],
            avisos=[Aviso(mensagem="amostra pequena", origem="Fake")],
        )

        resultado = analise.analisar([analisador], banco_curado)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == [Aviso(mensagem="amostra pequena", origem="Fake")]


class TestErro:
    """Erro esperado."""

    def test_analisar_propaga_falha_do_primeiro_analisador_que_falha(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Falha de um Analisador interrompe a composição e vira Falha."""
        banco_curado = _banco_curado(fabrica_tabela_extraida, fabrica_tabela_curada)
        analisador = AnalisadorFake(falha="métrica não calculável")

        resultado = analise.analisar([analisador], banco_curado)

        assert isinstance(resultado, Falha)
        assert "métrica não calculável" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_analisar_devolve_avisos_mesmo_em_falha(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Avisos acumulados antes da falha não são perdidos na Falha final."""
        banco_curado = _banco_curado(fabrica_tabela_extraida, fabrica_tabela_curada)
        analisador_com_aviso = AnalisadorFake(
            produz=[MetricaFake],
            avisos=[Aviso(mensagem="amostra pequena", origem="Fake")],
        )
        analisador_que_falha = AnalisadorFake(falha="métrica não calculável")

        resultado = analise.analisar(
            [analisador_com_aviso, analisador_que_falha], banco_curado
        )

        assert isinstance(resultado, Falha)
        assert resultado.avisos == [Aviso(mensagem="amostra pequena", origem="Fake")]

    def test_analisar_com_banco_curado_de_multiplas_tabelas(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """BancoAnalisado preserva todas as tabelas do BancoCurado de entrada."""
        tabela_1 = fabrica_tabela_extraida("public", "clientes")
        tabela_2 = fabrica_tabela_extraida("public", "pedidos")
        banco_curado = BancoCurado(
            tabelas=[
                fabrica_tabela_curada(tabela_1),
                fabrica_tabela_curada(tabela_2),
            ]
        )

        resultado = analise.analisar([], banco_curado)

        assert isinstance(resultado, Sucesso)
        nomes = {tabela.nome_tabela for tabela in resultado.valor.tabelas}
        assert nomes == {"clientes", "pedidos"}

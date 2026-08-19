"""Testes do núcleo de Port da etapa de extração (sem UI)."""

from collections.abc import Callable

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline.comum.estagio import Estagio
from ddf.pipeline.etapas import extracao


class ExtratorFake:
    """Extrator fake com respostas programadas, sem lógica real de conexão."""

    def __init__(
        self,
        resposta_escopos: Sucesso[list[str]] | Falha | None = None,
        respostas_tabelas: dict[str, Sucesso[list[tuple[str, str]]] | Falha]
        | None = None,
    ) -> None:
        """Guarda as respostas programadas de listar_escopos()/listar_tabelas()."""
        self._resposta_escopos = resposta_escopos
        self._respostas_tabelas = respostas_tabelas or {}

    def listar_escopos(self) -> Sucesso[list[str]] | Falha:
        """Devolve a resposta programada."""
        assert self._resposta_escopos is not None
        return self._resposta_escopos

    def listar_tabelas(self, escopo: str, /) -> Sucesso[list[tuple[str, str]]] | Falha:
        """Devolve a resposta programada para o escopo informado."""
        return self._respostas_tabelas[escopo]

    def extrair_tabela(
        self, escopo: str, tabela: str, /
    ) -> Sucesso[TabelaExtraida] | Falha:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(
        self, resultado_extrair: Sucesso[list[TabelaExtraida]] | Falha
    ) -> None:
        """Guarda o Resultado que extrair() sempre devolve, e registra chamadas."""
        self._resultado_extrair = resultado_extrair
        self.pares_recebidos: list[tuple[str, str]] | None = None

    def extrair(
        self,
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Sucesso[list[TabelaExtraida]] | Falha:
        """Registra os pares recebidos e chama progresso por item, se houver."""
        self.pares_recebidos = pares
        if progresso is not None:
            for escopo, tabela in pares:
                progresso(f"{escopo}.{tabela}")
        return self._resultado_extrair

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Sucesso[BancoCurado] | Falha:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class TestFeliz:
    """Caminho feliz."""

    def test_testar_conexao_devolve_escopos_do_extrator(self) -> None:
        """Repassa o Sucesso de listar_escopos() sem alteração."""
        extrator = ExtratorFake(resposta_escopos=Sucesso(valor=["public", "vendas"]))

        resultado = extracao.testar_conexao(extrator)

        assert resultado == Sucesso(valor=["public", "vendas"])

    def test_listar_pares_agrega_tabelas_de_multiplos_escopos_sem_avisos(
        self,
    ) -> None:
        """Todos os escopos respondem com sucesso — nenhum Aviso emitido."""
        extrator = ExtratorFake(
            respostas_tabelas={
                "public": Sucesso(valor=[("public", "clientes")]),
                "vendas": Sucesso(
                    valor=[("vendas", "pedidos"), ("vendas", "itens")]
                ),
            }
        )

        pares, avisos = extracao.listar_pares(extrator, ["public", "vendas"])

        assert pares == [
            ("public", "clientes"),
            ("vendas", "pedidos"),
            ("vendas", "itens"),
        ]
        assert avisos == []

    def test_extrair_tabelas_devolve_resultado_do_orquestrador(
        self, fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida]
    ) -> None:
        """Repassa o Sucesso de orquestrador.extrair() sem alteração."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))

        resultado = extracao.extrair_tabelas(
            orquestrador, ExtratorFake(), [("public", "clientes")]
        )

        assert resultado == Sucesso(valor=[tabela])
        assert orquestrador.pares_recebidos == [("public", "clientes")]


class TestErro:
    """Erro esperado."""

    def test_testar_conexao_propaga_falha_de_conexao(self) -> None:
        """Repassa a Falha de listar_escopos() sem alteração."""
        extrator = ExtratorFake(resposta_escopos=Falha(erro="conexão recusada"))

        resultado = extracao.testar_conexao(extrator)

        assert resultado == Falha(erro="conexão recusada")

    def test_extrair_tabelas_propaga_falha_do_orquestrador(self) -> None:
        """Repassa a Falha de orquestrador.extrair() sem alteração."""
        orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela extraída"))

        resultado = extracao.extrair_tabelas(
            orquestrador, ExtratorFake(), [("public", "clientes")]
        )

        assert resultado == Falha(erro="nenhuma tabela extraída")


class TestBorda:
    """Bordas."""

    def test_listar_pares_escopo_com_falha_vira_aviso_sem_abortar_demais(
        self,
    ) -> None:
        """Escopo com falha de listagem não impede os demais — sucesso parcial."""
        extrator = ExtratorFake(
            respostas_tabelas={
                "public": Sucesso(valor=[("public", "clientes")]),
                "financeiro_typo": Falha("Escopo 'financeiro_typo' não encontrado."),
            }
        )

        pares, avisos = extracao.listar_pares(
            extrator, ["public", "financeiro_typo"]
        )

        assert pares == [("public", "clientes")]
        assert len(avisos) == 1
        assert "financeiro_typo" in avisos[0].mensagem
        assert "Escopo 'financeiro_typo' não encontrado." in avisos[0].mensagem

    def test_listar_pares_todos_escopos_falhando_devolve_pares_vazios(
        self,
    ) -> None:
        """Todos os escopos falham — pares vazios, um Aviso por escopo."""
        extrator = ExtratorFake(
            respostas_tabelas={
                "a": Falha("erro a"),
                "b": Falha("erro b"),
            }
        )

        pares, avisos = extracao.listar_pares(extrator, ["a", "b"])

        assert pares == []
        assert len(avisos) == 2

    def test_extrair_tabelas_repassa_progresso_ao_orquestrador(
        self, fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida]
    ) -> None:
        """O callback de progresso chega intacto até o orquestrador."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=[tabela]))
        eventos: list[str] = []

        extracao.extrair_tabelas(
            orquestrador,
            ExtratorFake(),
            [("public", "clientes")],
            progresso=eventos.append,
        )

        assert eventos == ["public.clientes"]

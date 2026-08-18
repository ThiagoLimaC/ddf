"""Testes do núcleo de Port da etapa de curadoria (sem UI)."""

from collections.abc import Callable

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline import curadoria
from ddf.pipeline.estagio import Estagio


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(
        self, resultado_aplicar_sobrescritas: Sucesso[BancoCurado] | Falha
    ) -> None:
        """Guarda o Resultado que aplicar_sobrescritas() sempre devolve."""
        self._resultado = resultado_aplicar_sobrescritas
        self.tabelas_recebidas: list[TabelaExtraida] | None = None

    def extrair(
        self,
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Sucesso[list[TabelaExtraida]] | Falha:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Sucesso[BancoCurado] | Falha:
        """Registra as tabelas recebidas e chama progresso por item, se houver."""
        self.tabelas_recebidas = tabelas
        if progresso is not None:
            for tabela in tabelas:
                progresso(f"{tabela.nome_escopo}.{tabela.nome_tabela}")
        return self._resultado


def _sobrescrita_fake(tabela: TabelaExtraida) -> Sucesso[TabelaCurada]:
    """Não é exercitada de verdade — só precisa satisfazer o tipo Estagio."""
    raise NotImplementedError


class TestFeliz:
    """Caminho feliz."""

    def test_aplica_sobrescritas_devolve_banco_curado_do_orquestrador(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Repassa o Sucesso de orquestrador.aplicar_sobrescritas() sem alteração."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        banco = BancoCurado(tabelas=[fabrica_tabela_curada(tabela)])
        orquestrador = OrquestradorFake(Sucesso(valor=banco))

        resultado = curadoria.aplicar_sobrescritas_em_lote(
            orquestrador, _sobrescrita_fake, [tabela]
        )

        assert resultado == Sucesso(valor=banco)
        assert orquestrador.tabelas_recebidas == [tabela]


class TestErro:
    """Erro esperado."""

    def test_aplica_sobrescritas_propaga_falha_do_orquestrador(
        self, fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida]
    ) -> None:
        """Repassa a Falha de orquestrador.aplicar_sobrescritas() sem alteração."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela curada"))

        resultado = curadoria.aplicar_sobrescritas_em_lote(
            orquestrador, _sobrescrita_fake, [tabela]
        )

        assert resultado == Falha(erro="nenhuma tabela curada")


class TestBorda:
    """Bordas."""

    def test_reusada_por_duas_chamadas_com_os_mesmos_argumentos(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        fabrica_tabela_curada: Callable[[TabelaExtraida], TabelaCurada],
    ) -> None:
        """Mesma função serve tanto para gerar skeletons quanto reaplicar depois.

        `SobrescritaDeTabela` relê o YAML do disco a cada chamada — a
        função não guarda estado entre as duas invocações, então chamar
        duas vezes com os mesmos argumentos é seguro e não mascara edição
        feita pelo usuário entre a 1ª e a 2ª passada.
        """
        tabela = fabrica_tabela_extraida("public", "clientes")
        banco = BancoCurado(tabelas=[fabrica_tabela_curada(tabela)])
        orquestrador = OrquestradorFake(Sucesso(valor=banco))

        primeira = curadoria.aplicar_sobrescritas_em_lote(
            orquestrador, _sobrescrita_fake, [tabela]
        )
        segunda = curadoria.aplicar_sobrescritas_em_lote(
            orquestrador, _sobrescrita_fake, [tabela]
        )

        assert primeira == segunda == Sucesso(valor=banco)

    def test_repassa_progresso_ao_orquestrador(
        self, fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida]
    ) -> None:
        """O callback de progresso chega intacto até o orquestrador."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Falha(erro="não exercitado"))
        eventos: list[str] = []

        curadoria.aplicar_sobrescritas_em_lote(
            orquestrador, _sobrescrita_fake, [tabela], progresso=eventos.append
        )

        assert eventos == ["public.clientes"]

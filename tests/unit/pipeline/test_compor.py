"""Testes de compor()."""

from collections.abc import Callable

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.compor import compor
from ddf.pipeline.estagio import Estagio

EstagioInt = Callable[[int], Resultado[int]]
FabricaEstagioSucesso = Callable[[int, "list[Aviso] | None"], EstagioInt]
FabricaEstagioFalha = Callable[[str, "list[Aviso] | None"], EstagioInt]


class TestFeliz:
    """Caminho feliz."""

    def test_compor_executa_estagios_em_sequencia_acumulando_avisos(
        self, fabrica_estagio_sucesso: FabricaEstagioSucesso
    ) -> None:
        """Valor passa adiante, avisos são acumulados em ordem."""
        aviso1 = Aviso(mensagem="etapa 1", origem="Estagio1")
        aviso2 = Aviso(mensagem="etapa 2", origem="Estagio2")
        pipeline = compor(
            fabrica_estagio_sucesso(1, [aviso1]),
            fabrica_estagio_sucesso(10, [aviso2]),
        )

        resultado = pipeline(0)

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == 11
        assert resultado.avisos == [aviso1, aviso2]


class TestErro:
    """Erro esperado."""

    def test_compor_para_no_primeiro_erro_sem_rodar_estagios_seguintes(
        self,
        fabrica_estagio_sucesso: FabricaEstagioSucesso,
        fabrica_estagio_falha: FabricaEstagioFalha,
        estagio_espiao: EstagioInt,
    ) -> None:
        """compor() interrompe no 1º erro, sem rodar os seguintes."""
        pipeline = compor(
            fabrica_estagio_sucesso(1, None),
            fabrica_estagio_falha("erro fatal na etapa 2", None),
            estagio_espiao,
        )

        resultado = pipeline(0)

        assert isinstance(resultado, Falha)
        assert resultado.erro == "erro fatal na etapa 2"
        assert estagio_espiao.chamado is False  # type: ignore[attr-defined]

    def test_compor_converte_excecao_nao_prevista_em_falha(
        self,
        fabrica_estagio_sucesso: FabricaEstagioSucesso,
        estagio_espiao: EstagioInt,
    ) -> None:
        """Estagio que levanta Exception vira Falha, não propaga crua.

        Reproduz o boundary sistemático da issue #56 — nenhum Estagio (nem
        Analisador nem qualquer outro) tinha essa rede de segurança antes.
        Estagios seguintes não rodam, mesmo comportamento de Falha explícita.
        """

        def _estagio_com_bug(entrada: int) -> Resultado[int]:
            raise ValueError("dtype não suportado")

        pipeline = compor(
            fabrica_estagio_sucesso(1, None), _estagio_com_bug, estagio_espiao
        )

        resultado = pipeline(0)

        assert isinstance(resultado, Falha)
        assert "ValueError" in resultado.erro
        assert "dtype não suportado" in resultado.erro
        assert estagio_espiao.chamado is False  # type: ignore[attr-defined]


class TestBorda:
    """Bordas."""

    def test_compor_preserva_avisos_acumulados_ate_a_falha(
        self,
        fabrica_estagio_sucesso: FabricaEstagioSucesso,
        fabrica_estagio_falha: FabricaEstagioFalha,
    ) -> None:
        """Falha final carrega avisos das etapas anteriores e da própria falha."""
        aviso_previo = Aviso(mensagem="etapa 1 ok, mas atenção", origem="Estagio1")
        aviso_da_falha = Aviso(mensagem="ainda deu pra emitir isso", origem="Estagio2")
        pipeline = compor(
            fabrica_estagio_sucesso(1, [aviso_previo]),
            fabrica_estagio_falha("erro fatal na etapa 2", [aviso_da_falha]),
        )

        resultado = pipeline(0)

        assert isinstance(resultado, Falha)
        assert resultado.avisos == [aviso_previo, aviso_da_falha]

    def test_compor_sem_estagios_retorna_entrada_inalterada(self) -> None:
        """compor() sem nenhum estagio (ex.: usuário não seleciona Analisadores)."""
        pipeline: Estagio[int, int] = compor()

        resultado = pipeline(42)

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == 42
        assert resultado.avisos == []

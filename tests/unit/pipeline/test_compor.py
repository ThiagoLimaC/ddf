"""Testes de compor()."""

from tests.unit.pipeline.conftest import (
    EstagioInt,
    FabricaEstagioFalha,
    FabricaEstagioSucesso,
)

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline.compor import compor


def test_compor_executa_estagios_em_sequencia_acumulando_avisos(
    fabrica_estagio_sucesso: FabricaEstagioSucesso,
) -> None:
    """Caminho feliz: valor passa adiante, avisos são acumulados em ordem."""
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


def test_compor_para_no_primeiro_erro_sem_rodar_estagios_seguintes(
    fabrica_estagio_sucesso: FabricaEstagioSucesso,
    fabrica_estagio_falha: FabricaEstagioFalha,
    estagio_espiao: EstagioInt,
) -> None:
    """Erro esperado: compor() interrompe no 1º erro, sem rodar os seguintes."""
    pipeline = compor(
        fabrica_estagio_sucesso(1, None),
        fabrica_estagio_falha("erro fatal na etapa 2", None),
        estagio_espiao,
    )

    resultado = pipeline(0)

    assert isinstance(resultado, Falha)
    assert resultado.erro == "erro fatal na etapa 2"
    assert estagio_espiao.chamado is False  # type: ignore[attr-defined]


def test_compor_preserva_avisos_acumulados_ate_a_falha(
    fabrica_estagio_sucesso: FabricaEstagioSucesso,
    fabrica_estagio_falha: FabricaEstagioFalha,
) -> None:
    """Borda: Falha final carrega avisos das etapas anteriores e da própria falha."""
    aviso_previo = Aviso(mensagem="etapa 1 ok, mas atenção", origem="Estagio1")
    aviso_da_falha = Aviso(mensagem="ainda deu pra emitir isso", origem="Estagio2")
    pipeline = compor(
        fabrica_estagio_sucesso(1, [aviso_previo]),
        fabrica_estagio_falha("erro fatal na etapa 2", [aviso_da_falha]),
    )

    resultado = pipeline(0)

    assert isinstance(resultado, Falha)
    assert resultado.avisos == [aviso_previo, aviso_da_falha]


def test_compor_sem_estagios_retorna_entrada_inalterada() -> None:
    """Borda: compor() sem nenhum estagio (ex.: usuário não seleciona Analisadores)."""
    pipeline = compor()

    resultado = pipeline(42)

    assert isinstance(resultado, Sucesso)
    assert resultado.valor == 42
    assert resultado.avisos == []

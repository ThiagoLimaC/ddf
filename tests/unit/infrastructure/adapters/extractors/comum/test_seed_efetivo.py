"""Testes de seed_efetivo."""

from ddf.infrastructure.adapters.extractors.comum.seed_efetivo import seed_efetivo

# Caminho feliz


def test_seed_informado_e_retornado_sem_alteracao() -> None:
    """Caminho feliz: seed explícito do usuário é sempre respeitado."""
    assert seed_efetivo(42) == 42


# Erro esperado — não se aplica: função pura, sem I/O, sem exceção esperada.


# Borda


def test_seed_ausente_gera_um_valor_inteiro() -> None:
    """Borda: sem seed do usuário, gera um inteiro não-negativo, nunca None."""
    gerado = seed_efetivo(None)

    assert isinstance(gerado, int)
    assert gerado >= 0


def test_seed_zero_e_respeitado_sem_gerar_outro() -> None:
    """Borda: seed=0 é um valor explícito válido, não deve ser tratado como ausente."""
    assert seed_efetivo(0) == 0

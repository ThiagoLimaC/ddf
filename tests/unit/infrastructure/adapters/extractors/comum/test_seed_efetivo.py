"""Testes de seed_efetivo."""

from ddf.infrastructure.adapters.extractors.comum.seed_efetivo import seed_efetivo


class TestFeliz:
    """Caminho feliz."""

    def test_seed_informado_e_retornado_sem_alteracao(
        self,
    ) -> None:
        """Seed explícito do usuário é sempre respeitado."""
        assert seed_efetivo(42) == 42


class TestBorda:
    """Bordas."""

    def test_seed_ausente_gera_um_valor_inteiro(
        self,
    ) -> None:
        """Sem seed do usuário, gera um inteiro não-negativo, nunca None."""
        gerado = seed_efetivo(None)

        assert isinstance(gerado, int)
        assert gerado >= 0

    def test_seed_zero_e_respeitado_sem_gerar_outro(
        self,
    ) -> None:
        """seed=0 é um valor explícito válido, não deve ser tratado como ausente."""
        assert seed_efetivo(0) == 0

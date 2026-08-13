"""Testes de seed_efetivo."""

from ddf.infrastructure.adapters.extractors.comum.seed_efetivo import (
    _SEED_PADRAO,
    seed_efetivo,
)


class TestFeliz:
    """Caminho feliz."""

    def test_seed_informado_e_retornado_sem_alteracao(
        self,
    ) -> None:
        """Seed explícito do usuário é sempre respeitado."""
        assert seed_efetivo(42) == 42


class TestBorda:
    """Bordas."""

    def test_seed_ausente_usa_o_padrao_fixo_do_ddf(
        self,
    ) -> None:
        """Sem seed do usuário, usa a constante fixa — nunca None, nunca aleatório."""
        assert seed_efetivo(None) == _SEED_PADRAO

    def test_seed_ausente_e_estavel_entre_chamadas(
        self,
    ) -> None:
        """O valor default não varia entre chamadas — é o que dá diff estável."""
        assert seed_efetivo(None) == seed_efetivo(None)

    def test_seed_zero_e_respeitado_sem_gerar_outro(
        self,
    ) -> None:
        """seed=0 é um valor explícito válido, não deve ser tratado como ausente."""
        assert seed_efetivo(0) == 0

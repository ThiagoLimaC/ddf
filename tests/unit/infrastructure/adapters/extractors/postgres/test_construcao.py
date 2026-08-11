"""Testes de particoes_de_blocos."""

from ddf.infrastructure.adapters.extractors.postgres._construcao import (
    particoes_de_blocos,
)


class TestFeliz:
    """Caminho feliz."""

    def test_divide_em_faixas_do_mesmo_tamanho(self) -> None:
        """1000 blocos em 4 faixas -> 250 blocos cada, contíguas."""
        faixas = particoes_de_blocos(total_blocos=1000, n=4)

        assert faixas == [(0, 250), (250, 500), (500, 750), (750, None)]

    def test_ultima_faixa_nao_tem_teto(self) -> None:
        """A última faixa é sempre aberta (fim=None), nunca fechada."""
        faixas = particoes_de_blocos(total_blocos=100, n=2)

        assert faixas[-1][1] is None


class TestBorda:
    """Casos de borda."""

    def test_n_igual_a_um_devolve_faixa_unica_aberta(self) -> None:
        """Sem paralelismo de verdade — 1 faixa cobrindo tudo."""
        faixas = particoes_de_blocos(total_blocos=500, n=1)

        assert faixas == [(0, None)]

    def test_tabela_vazia_ainda_gera_faixas_validas(self) -> None:
        """0 blocos não deve gerar faixas degeneradas (início > fim)."""
        faixas = particoes_de_blocos(total_blocos=0, n=3)

        assert faixas == [(0, 1), (1, 2), (2, None)]

    def test_n_maior_que_total_de_blocos_ainda_e_disjunto_e_exaustivo(self) -> None:
        """Mais faixas pedidas do que blocos existentes — sem overlap nem gap."""
        faixas = particoes_de_blocos(total_blocos=3, n=10)

        inicios_e_fins = [(inicio, fim) for inicio, fim in faixas[:-1]]
        assert all(fim - inicio >= 1 for inicio, fim in inicios_e_fins)
        # Disjunto: cada faixa começa exatamente onde a anterior termina.
        for (_, fim_anterior), (inicio_atual, _) in zip(faixas, faixas[1:]):
            assert fim_anterior == inicio_atual

    def test_resto_da_divisao_fica_todo_na_ultima_faixa(self) -> None:
        """total_blocos não múltiplo de n — a sobra vai pra faixa aberta final."""
        faixas = particoes_de_blocos(total_blocos=10, n=3)

        assert faixas == [(0, 3), (3, 6), (6, None)]


class TestErro:
    """Uso indevido."""

    def test_n_zero_ou_negativo_devolve_lista_vazia(self) -> None:
        """`n <= 0` não faz sentido como número de faixas — devolve vazio."""
        assert particoes_de_blocos(total_blocos=100, n=0) == []
        assert particoes_de_blocos(total_blocos=100, n=-1) == []

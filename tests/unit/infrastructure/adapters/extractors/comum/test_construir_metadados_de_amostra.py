"""Testes de construir_metadados_de_amostra."""

from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
)
from ddf.infrastructure.adapters.extractors.comum.construir_metadados_de_amostra import (  # noqa: E501
    construir_metadados_de_amostra,
)


class TestFeliz:
    """Caminho feliz."""

    def test_amostragem_probabilistica_registra_percentual_e_seed(
        self,
    ) -> None:
        """percentual/seed efetivos ficam em MetadadosDeAmostra."""
        metadados, avisos = construir_metadados_de_amostra(
            nome="percentual_de_linhas",
            requisicao=AmostragemProbabilistica(percentual=10.0, seed=42),
            tamanho_amostra=1_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="public.clientes",
        )

        assert metadados.estrategia == "percentual_de_linhas"
        assert metadados.tamanho_amostra == 1_000
        assert metadados.percentual == 10.0
        assert metadados.seed == 42
        assert len(avisos) == 1
        assert "varredura sequencial completa" in avisos[0].mensagem

    def test_amostragem_integral_nao_registra_percentual_nem_seed(
        self,
    ) -> None:
        """tabela_inteira não tem política probabilística — ambos None."""
        metadados, avisos = construir_metadados_de_amostra(
            nome="tabela_inteira",
            requisicao=AmostragemIntegral(),
            tamanho_amostra=10_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="public.clientes",
        )

        assert metadados.percentual is None
        assert metadados.seed is None
        assert avisos == []


class TestBorda:
    """Bordas."""

    def test_amostragem_probabilistica_aviso_de_custo_cita_tabela_e_total_linhas(
        self,
    ) -> None:
        """Mensagem do Aviso de custo cita a tabela e total_linhas.

        Sem o identificador, os exemplos que avisos.py mostra antes de colapsar
        por contagem ficam anônimos — o usuário não sabe qual tabela específica
        paga o custo (issue #75).
        """
        _metadados, avisos = construir_metadados_de_amostra(
            nome="percentual_de_linhas",
            requisicao=AmostragemProbabilistica(percentual=1.0),
            tamanho_amostra=500_000,
            total_linhas=50_000_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="vendas.pedidos",
        )

        assert len(avisos) == 1
        assert avisos[0].origem == "ExtratorFake"
        assert "vendas.pedidos" in avisos[0].mensagem
        assert "50000000" in avisos[0].mensagem

    def test_amostra_maior_que_total_linhas_soma_ao_aviso_de_custo(
        self,
    ) -> None:
        """Amostra maior que a estimativa de catálogo soma um 2º Aviso."""
        _metadados, avisos = construir_metadados_de_amostra(
            nome="percentual_de_linhas",
            requisicao=AmostragemProbabilistica(percentual=100.0),
            tamanho_amostra=12_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="vendas.pedidos",
        )

        assert len(avisos) == 2
        aviso_divergencia = avisos[1]
        assert aviso_divergencia.origem == "ExtratorFake"
        assert "vendas.pedidos" in aviso_divergencia.mensagem
        assert "12000" in aviso_divergencia.mensagem
        assert "10000" in aviso_divergencia.mensagem
        assert "sem ANALYZE recente" in aviso_divergencia.mensagem

    def test_amostragem_integral_nunca_diverge_de_total_linhas(
        self,
    ) -> None:
        """Quando o chamador passa total_linhas=len(amostra), nunca há Aviso.

        Reflete o invariante real do Extrator: em AmostragemIntegral, total_linhas
        É o tamanho da amostra (mesma variável) — não um caso especial tratado
        aqui dentro.
        """
        _metadados, avisos = construir_metadados_de_amostra(
            nome="tabela_inteira",
            requisicao=AmostragemIntegral(),
            tamanho_amostra=10_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="public.clientes",
        )

        assert avisos == []

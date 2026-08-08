"""Testes de construir_metadados_de_amostra."""

from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoPorFaixa,
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
        assert avisos == []

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

    def test_requisicao_por_faixa_registra_percentual_e_seed_sem_aviso(
        self,
    ) -> None:
        """percentual/seed ficam em MetadadosDeAmostra; sem Aviso por tabela.

        O aviso de viés de cluster saiu daqui na #116 — passou a ser avisado
        uma vez, na escolha da estratégia (`cli/registro/estrategias.py::
        _construir_amostragem_por_faixa`), não mais por tabela extraída.
        """
        metadados, avisos = construir_metadados_de_amostra(
            nome="amostragem_por_faixa",
            requisicao=RequisicaoPorFaixa(percentual=10.0, seed=42),
            tamanho_amostra=1_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="public.clientes",
        )

        assert metadados.estrategia == "amostragem_por_faixa"
        assert metadados.percentual == 10.0
        assert metadados.seed == 42
        assert avisos == []


class TestBorda:
    """Bordas."""

    def test_amostra_maior_que_total_linhas_emite_aviso_de_divergencia(
        self,
    ) -> None:
        """Amostra maior que a estimativa de catálogo emite Aviso de divergência."""
        _metadados, avisos = construir_metadados_de_amostra(
            nome="percentual_de_linhas",
            requisicao=AmostragemProbabilistica(percentual=100.0),
            tamanho_amostra=12_000,
            total_linhas=10_000,
            origem="ExtratorFake",
            causa_provavel="sem ANALYZE recente",
            identificador_tabela="vendas.pedidos",
        )

        assert len(avisos) == 1
        aviso_divergencia = avisos[0]
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

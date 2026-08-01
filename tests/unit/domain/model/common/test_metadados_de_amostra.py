"""Testes de MetadadosDeAmostra."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra


class TestFeliz:
    """Caminho feliz."""

    def test_cria_metadados_com_estrategia_e_tamanho_amostra(
        self, metadados_de_amostra: MetadadosDeAmostra
    ) -> None:
        """MetadadosDeAmostra guarda estrategia e tamanho_amostra."""
        assert metadados_de_amostra.estrategia == "percentual_de_linhas"
        assert metadados_de_amostra.tamanho_amostra == 10_000

    def test_guarda_percentual_e_seed_efetivos(self) -> None:
        """Percentual e seed efetivamente usados ficam registrados."""
        metadados = MetadadosDeAmostra(
            estrategia="percentual_de_linhas",
            tamanho_amostra=1_000,
            percentual=10.0,
            seed=42,
        )

        assert metadados.percentual == 10.0
        assert metadados.seed == 42


class TestErro:
    """Erro esperado."""

    def test_tamanho_amostra_negativo_levanta_validation_error(self) -> None:
        """tamanho_amostra negativo é logicamente impossível."""
        with pytest.raises(ValidationError, match="tamanho_amostra"):
            MetadadosDeAmostra(estrategia="percentual_de_linhas", tamanho_amostra=-1)


class TestBorda:
    """Bordas."""

    def test_metadados_de_amostra_e_imutavel(
        self, metadados_de_amostra: MetadadosDeAmostra
    ) -> None:
        """MetadadosDeAmostra é imutável após construção (frozen=True)."""
        with pytest.raises(ValidationError):
            metadados_de_amostra.tamanho_amostra = 20_000

    def test_tamanho_amostra_zero_e_aceito(self) -> None:
        """Tabela vazia (0 linhas amostradas) é um estado real e válido."""
        metadados = MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=0
        )

        assert metadados.tamanho_amostra == 0

    def test_percentual_e_seed_sao_opcionais_e_default_para_none(self) -> None:
        """tabela_inteira não tem percentual/seed — ambos None por padrão."""
        metadados = MetadadosDeAmostra(
            estrategia="tabela_inteira", tamanho_amostra=10_000
        )

        assert metadados.percentual is None
        assert metadados.seed is None

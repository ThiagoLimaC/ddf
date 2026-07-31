"""Testes de RestricaoUnica."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.restricao_unica import RestricaoUnica


class TestFeliz:
    """Caminho feliz."""

    def test_restricao_unica_guarda_colunas_em_ordem(self) -> None:
        """RestricaoUnica guarda as colunas na ordem informada."""
        restricao = RestricaoUnica(colunas=("codigo_pais", "codigo_local"))

        assert restricao.colunas == ("codigo_pais", "codigo_local")

    def test_restricao_unica_aceita_mais_de_duas_colunas(self) -> None:
        """RestricaoUnica não limita o número de colunas a 2."""
        restricao = RestricaoUnica(colunas=("a", "b", "c"))

        assert restricao.colunas == ("a", "b", "c")


class TestErro:
    """Erro esperado."""

    def test_restricao_unica_com_uma_coluna_levanta_validation_error(self) -> None:
        """1 coluna não é composta — pertence ao campo `unica`."""
        with pytest.raises(ValidationError, match="mínimo 2 colunas"):
            RestricaoUnica(colunas=("id",))

    def test_restricao_unica_sem_coluna_levanta_validation_error(self) -> None:
        """Lista vazia não representa nenhuma constraint real."""
        with pytest.raises(ValidationError, match="mínimo 2 colunas"):
            RestricaoUnica(colunas=())

    def test_restricao_unica_com_coluna_duplicada_levanta_validation_error(
        self,
    ) -> None:
        """Mesma coluna repetida não é uma constraint válida."""
        with pytest.raises(ValidationError, match="duplicadas"):
            RestricaoUnica(colunas=("codigo", "codigo"))


class TestBorda:
    """Bordas."""

    def test_restricao_unica_e_imutavel(self) -> None:
        """RestricaoUnica é imutável após construção (frozen=True)."""
        restricao = RestricaoUnica(colunas=("a", "b"))

        with pytest.raises(ValidationError):
            restricao.colunas = ("a", "c")  # type: ignore[misc]

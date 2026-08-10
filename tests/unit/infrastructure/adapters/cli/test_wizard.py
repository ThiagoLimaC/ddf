"""Testes de _sair_se_vazio — os dois pontos de saída antecipada do wizard."""

import pytest

from ddf.infrastructure.adapters.cli.wizard import _sair_se_vazio


class TestFeliz:
    """Caminho feliz."""

    def test_sair_se_vazio_com_lista_nao_vazia_nao_sai(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Lista com itens não imprime nada nem sai do processo."""
        _sair_se_vazio(["algo"], "Nenhum item processado com sucesso.")

        assert capsys.readouterr().out == ""


class TestErro:
    """Erro esperado."""

    def test_sair_se_vazio_com_lista_vazia_sai_com_codigo_1(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Lista vazia imprime a mensagem e sai com código 1."""
        with pytest.raises(SystemExit) as excinfo:
            _sair_se_vazio([], "Nenhuma tabela extraída com sucesso.")

        assert excinfo.value.code == 1
        assert "Nenhuma tabela extraída com sucesso." in capsys.readouterr().out

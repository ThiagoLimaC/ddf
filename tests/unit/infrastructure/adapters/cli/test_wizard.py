"""Testes de _sair_se_vazio — os dois pontos de saída antecipada do wizard."""

import pytest

from ddf.infrastructure.adapters.cli.wizard import _sair_se_vazio


# Caminho feliz
def test_sair_se_vazio_com_lista_nao_vazia_nao_sai(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Caminho feliz: lista com itens não imprime nada nem sai do processo."""
    _sair_se_vazio(["algo"], "Nenhum item processado com sucesso.")

    assert capsys.readouterr().out == ""


# Erro esperado
def test_sair_se_vazio_com_lista_vazia_sai_com_codigo_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Erro esperado: lista vazia imprime a mensagem e sai com código 1."""
    with pytest.raises(SystemExit) as excinfo:
        _sair_se_vazio([], "Nenhuma tabela extraída com sucesso.")

    assert excinfo.value.code == 1
    assert "Nenhuma tabela extraída com sucesso." in capsys.readouterr().out

"""Testes de ou_sair, exibir_avisos e _tipo_de_aviso."""

import pytest

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.cli.avisos import (
    _tipo_de_aviso,
    exibir_avisos,
    ou_sair,
)

# ou_sair — caminho feliz


def test_ou_sair_com_sucesso_devolve_o_valor() -> None:
    """Caminho feliz: Sucesso devolve o valor, sem sair do processo."""
    assert ou_sair(Sucesso(valor=42)) == 42


# ou_sair — erro esperado


def test_ou_sair_com_falha_imprime_erro_e_sai_com_codigo_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Erro esperado: Falha imprime a mensagem de erro e sai com código 1."""
    with pytest.raises(SystemExit) as excinfo:
        ou_sair(Falha(erro="Não foi possível conectar"))

    assert excinfo.value.code == 1
    assert "Não foi possível conectar" in capsys.readouterr().out


# ou_sair — borda


def test_ou_sair_com_sucesso_e_avisos_exibe_os_avisos_antes_de_devolver(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Borda: Sucesso com Avisos os exibe, mas ainda devolve o valor normalmente."""
    resultado = ou_sair(
        Sucesso(valor="ok", avisos=[Aviso(mensagem="amostra pequena", origem="X")])
    )

    assert resultado == "ok"
    assert "amostra pequena" in capsys.readouterr().out


# exibir_avisos — caminho feliz


def test_exibir_avisos_com_lista_vazia_nao_imprime_nada(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Caminho feliz: lista vazia de Avisos não produz nenhuma saída."""
    exibir_avisos([])

    assert capsys.readouterr().out == ""


def test_exibir_avisos_agrupa_por_origem(capsys: pytest.CaptureFixture[str]) -> None:
    """Caminho feliz: Avisos de origens diferentes aparecem em grupos separados."""
    exibir_avisos(
        [
            Aviso(mensagem="skeleton criado para 'a'", origem="SobrescritaDeTabela"),
            Aviso(mensagem="amostra pequena em 'b'", origem="AnalisadorDeColuna"),
        ]
    )

    saida = capsys.readouterr().out
    assert "[SobrescritaDeTabela] 1 aviso(s):" in saida
    assert "[AnalisadorDeColuna] 1 aviso(s):" in saida


# exibir_avisos — borda


def test_exibir_avisos_ate_o_limite_mostra_cada_mensagem_na_integra(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Borda: até 3 ocorrências do mesmo tipo, cada mensagem aparece por completo."""
    avisos = [
        Aviso(mensagem=f"skeleton criado para 't{i}'", origem="SobrescritaDeTabela")
        for i in range(3)
    ]

    exibir_avisos(avisos)

    saida = capsys.readouterr().out
    for i in range(3):
        assert f"skeleton criado para 't{i}'" in saida
    assert "(x3)" not in saida


def test_exibir_avisos_acima_do_limite_condensa_com_contagem_total(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Borda: acima do limite, condensa numa linha com a contagem total."""
    avisos = [
        Aviso(mensagem=f"skeleton criado para 't{i}'", origem="SobrescritaDeTabela")
        for i in range(5)
    ]

    exibir_avisos(avisos)

    saida = capsys.readouterr().out
    assert "skeleton criado para 't0'" in saida
    assert "skeleton criado para 't3'" not in saida
    assert "(x5)" in saida


# _tipo_de_aviso


def test_tipo_de_aviso_normaliza_identificador_e_numero() -> None:
    """Caminho feliz: identificadores entre aspas e números viram placeholder."""
    assert _tipo_de_aviso("Amostra pequena (N=5) em 'x.y.z'") == _tipo_de_aviso(
        "Amostra pequena (N=8) em 'a.b.c'"
    )


def test_tipo_de_aviso_preserva_mensagens_genuinamente_diferentes() -> None:
    """Borda: mensagens sem números/identificadores entre aspas continuam distintas."""
    assert _tipo_de_aviso("Amostra pequena") != _tipo_de_aviso("Coluna sem dados")

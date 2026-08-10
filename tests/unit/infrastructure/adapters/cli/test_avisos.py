"""Testes de ou_sair, exibir_avisos e _tipo_de_aviso."""

from typing import Any

import pytest

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.cli.avisos import (
    _tipo_de_aviso,
    exibir_avisos,
    ou_sair,
)

# ou_sair — caminho feliz


class TestFeliz:
    """Caminho feliz."""

    def test_ou_sair_com_sucesso_devolve_o_valor(
        self,
    ) -> None:
        """Sucesso devolve o valor, sem sair do processo."""
        assert ou_sair(Sucesso(valor=42)) == 42

    def test_exibir_avisos_com_lista_vazia_nao_imprime_nada(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Lista vazia de Avisos não produz nenhuma saída."""
        exibir_avisos([])

        assert interceptar_print == []

    def test_exibir_avisos_agrupa_por_origem(
        self, interceptar_print: list[dict[str, Any]]
    ) -> None:
        """Avisos de origens diferentes aparecem em grupos separados."""
        exibir_avisos(
            [
                Aviso(
                    mensagem="skeleton criado para 'a'", origem="SobrescritaDeTabela"
                ),
                Aviso(mensagem="amostra pequena em 'b'", origem="AnalisadorDeColuna"),
            ]
        )

        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("[SobrescritaDeTabela] 1 aviso(s):" in texto for texto in textos)
        assert any("[AnalisadorDeColuna] 1 aviso(s):" in texto for texto in textos)

    def test_tipo_de_aviso_normaliza_identificador_e_numero(
        self,
    ) -> None:
        """Identificadores entre aspas e números viram placeholder."""
        assert _tipo_de_aviso("Amostra pequena (N=5) em 'x.y.z'") == _tipo_de_aviso(
            "Amostra pequena (N=8) em 'a.b.c'"
        )


class TestErro:
    """Erro esperado."""

    def test_ou_sair_com_falha_imprime_erro_e_sai_com_codigo_1(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Falha imprime a mensagem de erro e sai com código 1."""
        with pytest.raises(SystemExit) as excinfo:
            ou_sair(Falha(erro="Não foi possível conectar"))

        assert excinfo.value.code == 1
        assert any(
            "Não foi possível conectar" in chamada["texto"]
            for chamada in interceptar_print
        )


class TestBorda:
    """Bordas."""

    def test_ou_sair_com_sucesso_e_avisos_exibe_os_avisos_antes_de_devolver(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Sucesso com Avisos os exibe, mas ainda devolve o valor normalmente."""
        resultado = ou_sair(
            Sucesso(valor="ok", avisos=[Aviso(mensagem="amostra pequena", origem="X")])
        )

        assert resultado == "ok"
        assert any(
            "amostra pequena" in chamada["texto"] for chamada in interceptar_print
        )

    def test_exibir_avisos_ate_o_limite_mostra_cada_mensagem_na_integra(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """até 3 ocorrências do mesmo tipo, cada mensagem aparece por completo."""
        avisos = [
            Aviso(mensagem=f"skeleton criado para 't{i}'", origem="SobrescritaDeTabela")
            for i in range(3)
        ]

        exibir_avisos(avisos)

        textos = [chamada["texto"] for chamada in interceptar_print]
        for i in range(3):
            assert any(f"skeleton criado para 't{i}'" in texto for texto in textos)
        assert not any("(x3)" in texto for texto in textos)

    def test_exibir_avisos_acima_do_limite_condensa_com_contagem_total(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Acima do limite, condensa numa linha com a contagem total."""
        avisos = [
            Aviso(mensagem=f"skeleton criado para 't{i}'", origem="SobrescritaDeTabela")
            for i in range(5)
        ]

        exibir_avisos(avisos)

        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("skeleton criado para 't0'" in texto for texto in textos)
        assert not any("skeleton criado para 't3'" in texto for texto in textos)
        assert any("(x5)" in texto for texto in textos)

    def test_tipo_de_aviso_preserva_mensagens_genuinamente_diferentes(
        self,
    ) -> None:
        """Mensagens sem números/identificadores entre aspas continuam distintas."""
        assert _tipo_de_aviso("Amostra pequena") != _tipo_de_aviso("Coluna sem dados")

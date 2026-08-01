"""Testes de Sucesso, Falha e Resultado[T]."""

import dataclasses

import pytest

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso


class TestFeliz:
    """Caminho feliz."""

    def test_sucesso_guarda_valor_e_avisos(self) -> None:
        """Sucesso guarda o valor e os avisos acumulados."""
        aviso = Aviso(mensagem="amostra pequena", origem="Estagio")
        resultado = Sucesso(valor=42, avisos=[aviso])

        assert resultado.valor == 42
        assert resultado.avisos == [aviso]


class TestErro:
    """Erro esperado."""

    def test_falha_guarda_mensagem_de_erro_legivel(self) -> None:
        """Falha guarda uma mensagem legível, sem traceback."""
        resultado = Falha(erro="Não foi possível conectar: timeout")

        assert resultado.erro == "Não foi possível conectar: timeout"
        assert resultado.avisos == []

    def test_sucesso_e_imutavel(self) -> None:
        """Tentar mutar um Sucesso levanta FrozenInstanceError."""
        resultado = Sucesso(valor=1)

        with pytest.raises(dataclasses.FrozenInstanceError):
            resultado.valor = 2  # type: ignore[misc]

    def test_falha_e_imutavel(self) -> None:
        """Tentar mutar uma Falha levanta FrozenInstanceError."""
        resultado = Falha(erro="erro qualquer")

        with pytest.raises(dataclasses.FrozenInstanceError):
            resultado.erro = "outro erro"  # type: ignore[misc]


class TestBorda:
    """Bordas."""

    def test_falha_pode_carregar_avisos_acumulados_antes_do_erro(self) -> None:
        """Falha carrega avisos emitidos antes da falha, sem descartá-los."""
        aviso = Aviso(mensagem="coluna sem dados", origem="Estagio1")
        resultado = Falha(erro="erro fatal no Estagio2", avisos=[aviso])

        assert resultado.avisos == [aviso]

    def test_avisos_default_nao_e_compartilhado_entre_instancias(self) -> None:
        """default_factory evita lista de avisos compartilhada por padrão mutável."""
        primeiro = Sucesso(valor=1)
        segundo = Sucesso(valor=2)

        primeiro.avisos.append(Aviso(mensagem="x", origem="y"))

        assert segundo.avisos == []

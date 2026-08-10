"""Testes das etapas 6-8 do wizard: skeletons, pausa e aplicação de sobrescritas."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ddf.domain.model.curation import BancoCurado
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.cli.etapas import curadoria
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)


class OrquestradorFake:
    """OrquestradorDeTabelas fake — devolve um Resultado pré-configurado."""

    def __init__(self, resultado: Resultado[BancoCurado]) -> None:
        """Guarda o Resultado que aplicar_sobrescritas() sempre devolve."""
        self._resultado = resultado

    def extrair(
        self, escopos: object, extrator: object, progresso: object = None
    ) -> Resultado[list[TabelaExtraida]]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def aplicar_sobrescritas(
        self, tabelas: object, sobrescrita: object, progresso: object = None
    ) -> Resultado[BancoCurado]:
        """Devolve o Resultado configurado, ignorando os argumentos."""
        return self._resultado


# curar() — caminho feliz


class TestFeliz:
    """Caminho feliz."""

    def test_curar_gera_skeletons_e_pausa_para_edicao_manual(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Gera skeletons, pausa e devolve a SobrescritaDeTabela."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        orquestrador = OrquestradorFake(Sucesso(valor=BancoCurado(tabelas=[])))
        pausas: list[str] = []
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.cli.prompts.pausar", pausas.append
        )

        sobrescrita = curadoria.curar(orquestrador, tmp_path, [tabela])  # type: ignore[arg-type]

        assert isinstance(sobrescrita, SobrescritaDeTabela)
        assert len(pausas) == 1

    def test_gerar_skeletons_conta_criados_e_preservados(
        self,
        interceptar_print: list[dict[str, Any]],
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Skeletons com Aviso contam como criados/atualizados."""
        tabelas = [
            fabrica_tabela_extraida("public", "clientes"),
            fabrica_tabela_extraida("public", "pedidos"),
        ]
        resultado = Sucesso(
            valor=BancoCurado(tabelas=[]),
            avisos=[
                Aviso(mensagem="skeleton criado para 'public.clientes'", origem="X")
            ],
        )
        orquestrador = OrquestradorFake(resultado)

        curadoria._gerar_skeletons(orquestrador, object(), tabelas)  # type: ignore[arg-type]

        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("1 skeleton(s) criado(s)/atualizado(s)" in texto for texto in textos)
        assert any("1 preservado(s) sem mudança." in texto for texto in textos)
        assert any("Preencha a curadoria e reexecute." in texto for texto in textos)
        assert not any(
            "skeleton criado para 'public.clientes'" in texto for texto in textos
        )

    def test_gerar_skeletons_sem_nenhum_criado_nao_sugere_reexecutar(
        self,
        interceptar_print: list[dict[str, Any]],
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Sem Aviso (tudo preservado), não há nada novo pra curar/reexecutar."""
        tabelas = [fabrica_tabela_extraida("public", "clientes")]
        orquestrador = OrquestradorFake(Sucesso(valor=BancoCurado(tabelas=[])))

        curadoria._gerar_skeletons(orquestrador, object(), tabelas)  # type: ignore[arg-type]

        assert not any(
            "Preencha a curadoria e reexecute." in chamada["texto"]
            for chamada in interceptar_print
        )

    def test_aplicar_sobrescritas_devolve_o_banco_curado(
        self,
    ) -> None:
        """Devolve o BancoCurado produzido pelo orquestrador."""
        banco = BancoCurado(tabelas=[])
        orquestrador = OrquestradorFake(Sucesso(valor=banco))

        resultado = curadoria.aplicar_sobrescritas(orquestrador, object(), [])  # type: ignore[arg-type]

        assert resultado == banco


class TestErro:
    """Erro esperado."""

    def test_gerar_skeletons_com_falha_sai_com_codigo_1(
        self,
    ) -> None:
        """Falha do orquestrador sai com código 1 antes de contar nada."""
        orquestrador = OrquestradorFake(Falha(erro="disco cheio"))

        with pytest.raises(SystemExit) as excinfo:
            curadoria._gerar_skeletons(orquestrador, object(), [])  # type: ignore[arg-type]

        assert excinfo.value.code == 1

    def test_aplicar_sobrescritas_com_falha_sai_com_codigo_1(
        self,
    ) -> None:
        """Falha do orquestrador sai com código 1."""
        orquestrador = OrquestradorFake(Falha(erro="nenhuma tabela curada"))

        with pytest.raises(SystemExit) as excinfo:
            curadoria.aplicar_sobrescritas(orquestrador, object(), [])  # type: ignore[arg-type]

        assert excinfo.value.code == 1

"""Testes das etapas 6-8 do wizard: skeletons, pausa e aplicação de sobrescritas.

`pipeline.curadoria` é fakeado em todos os testes — estes testes verificam
só comportamento de UI (contagem de criados/preservados, código de saída,
barra de progresso). O núcleo (chamada de OrquestradorDeTabelas.
aplicar_sobrescritas) é coberto em `tests/unit/pipeline/test_curadoria.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.inbounds.cli.etapas import curadoria
from ddf.infrastructure.adapters.outbounds.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)
from ddf.pipeline.comum.estagio import Estagio
from ddf.pipeline.etapas import curadoria as pipeline_curadoria


class _OrquestradorPlaceholder:
    """Satisfaz o Protocol OrquestradorDeTabelas estruturalmente — não é exercitado."""

    def extrair(
        self,
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Não é exercitado por estes testes — pipeline.curadoria é fakeado."""
        raise NotImplementedError


@dataclass
class _AplicarLoteFake:
    """Fake de pipeline.curadoria.aplicar_sobrescritas_em_lote.

    Chama `progresso` uma vez por tabela recebida, como o núcleo real faz,
    pra exercitar a barra de progresso real (não mockada) do wrapper de UI.
    """

    resultado: Resultado[BancoCurado]
    tabelas_recebidas: list[TabelaExtraida] | None = field(default=None, init=False)

    def __call__(
        self,
        orquestrador: OrquestradorDeTabelas,
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        tabelas: list[TabelaExtraida],
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Registra as tabelas recebidas e chama progresso por item, se houver."""
        self.tabelas_recebidas = tabelas
        if progresso is not None:
            for tabela in tabelas:
                progresso(f"{tabela.nome_escopo}.{tabela.nome_tabela}")
        return self.resultado


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
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Sucesso(valor=BancoCurado(tabelas=[]))),
        )
        pausas: list[str] = []
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.pausar", pausas.append
        )

        sobrescrita = curadoria.curar(
            _OrquestradorPlaceholder(), tmp_path, [tabela]
        )

        assert isinstance(sobrescrita, SobrescritaDeTabela)
        assert len(pausas) == 1

    def test_gerar_skeletons_conta_criados_e_preservados(
        self,
        monkeypatch: pytest.MonkeyPatch,
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
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(resultado),
        )

        curadoria._gerar_skeletons(_OrquestradorPlaceholder(), object(), tabelas)  # type: ignore[arg-type]

        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("1 skeleton(s) criado(s)/atualizado(s)" in texto for texto in textos)
        assert any("1 preservado(s) sem mudança." in texto for texto in textos)
        assert any("Preencha a curadoria e reexecute." in texto for texto in textos)
        assert not any(
            "skeleton criado para 'public.clientes'" in texto for texto in textos
        )

    def test_gerar_skeletons_sem_nenhum_criado_nao_sugere_reexecutar(
        self,
        monkeypatch: pytest.MonkeyPatch,
        interceptar_print: list[dict[str, Any]],
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Sem Aviso (tudo preservado), não há nada novo pra curar/reexecutar."""
        tabelas = [fabrica_tabela_extraida("public", "clientes")]
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Sucesso(valor=BancoCurado(tabelas=[]))),
        )

        curadoria._gerar_skeletons(_OrquestradorPlaceholder(), object(), tabelas)  # type: ignore[arg-type]

        assert not any(
            "Preencha a curadoria e reexecute." in chamada["texto"]
            for chamada in interceptar_print
        )

    def test_aplicar_sobrescritas_devolve_o_banco_curado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Devolve o BancoCurado produzido pelo pipeline."""
        banco = BancoCurado(tabelas=[])
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Sucesso(valor=banco)),
        )

        resultado = curadoria.aplicar_sobrescritas(
            _OrquestradorPlaceholder(), object(), []  # type: ignore[arg-type]
        )

        assert resultado == banco


class TestErro:
    """Erro esperado."""

    def test_gerar_skeletons_com_falha_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do pipeline sai com código 1 antes de contar nada."""
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Falha(erro="disco cheio")),
        )

        with pytest.raises(SystemExit) as excinfo:
            curadoria._gerar_skeletons(_OrquestradorPlaceholder(), object(), [])  # type: ignore[arg-type]

        assert excinfo.value.code == 1

    def test_aplicar_sobrescritas_com_falha_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do pipeline sai com código 1."""
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Falha(erro="nenhuma tabela curada")),
        )

        with pytest.raises(SystemExit) as excinfo:
            curadoria.aplicar_sobrescritas(_OrquestradorPlaceholder(), object(), [])  # type: ignore[arg-type]

        assert excinfo.value.code == 1


class TestBorda:
    """Bordas."""

    def test_gerar_skeletons_usa_progresso_paralelo_com_total_de_tabelas(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Barra real (não ampulheta) com o total de tabelas já conhecido."""
        tabelas = [
            fabrica_tabela_extraida("public", "clientes"),
            fabrica_tabela_extraida("public", "pedidos"),
        ]
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Sucesso(valor=BancoCurado(tabelas=[]))),
        )

        curadoria._gerar_skeletons(_OrquestradorPlaceholder(), object(), tabelas)  # type: ignore[arg-type]

        saida = capsys.readouterr().out
        assert "Skeletons gerados (2/2)" in saida

    def test_aplicar_sobrescritas_usa_progresso_paralelo_com_total_de_tabelas(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Barra real (não ampulheta) com o total de tabelas já conhecido."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        monkeypatch.setattr(
            pipeline_curadoria,
            "aplicar_sobrescritas_em_lote",
            _AplicarLoteFake(Sucesso(valor=BancoCurado(tabelas=[]))),
        )

        curadoria.aplicar_sobrescritas(_OrquestradorPlaceholder(), object(), [tabela])  # type: ignore[arg-type]

        saida = capsys.readouterr().out
        assert "Sobrescritas aplicadas (1/1)" in saida

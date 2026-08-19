"""Testes das etapas 12-14 do wizard: destino, confirmação e execução dos Geradores.

`pipeline.geracao.executar_geradores` é fakeado — estes testes verificam só
comportamento de UI (avisos, código de saída, exibição incremental por
Gerador). O núcleo (loop + `_slugificar` + `executar_com_seguranca`) é
coberto em `tests/unit/pipeline/test_geracao.py`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.inbounds.cli.etapas import geracao
from ddf.pipeline.etapas.geracao import ResultadoDeGerador


def _fake_pipeline_executar(
    itens: list[ResultadoDeGerador],
) -> Callable[..., list[ResultadoDeGerador]]:
    """Fake de pipeline.geracao.executar_geradores.

    Chama `progresso` uma vez por item, na ordem dada — como o núcleo real
    faz — pra exercitar a exibição incremental do wrapper de UI.
    """

    def _fn(
        nomes_geradores: list[str],
        geradores_registrados: dict[str, object],
        banco_analisado: BancoAnalisado,
        destino: Path,
        progresso: Callable[[ResultadoDeGerador], None] | None = None,
    ) -> list[ResultadoDeGerador]:
        if progresso is not None:
            for item in itens:
                progresso(item)
        return itens

    return _fn


class TestFeliz:
    """Caminho feliz."""

    def test_confirmar_execucao_aceita_e_nao_sai(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """confirmação aceita não interrompe o processo."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda mensagem: True
        )

        geracao.confirmar_execucao(
            ["Markdown"], tmp_path
        )  # não deve levantar SystemExit

    def test_executar_geradores_com_sucesso_nao_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Todos os Geradores escolhidos rodam com sucesso."""
        item = ResultadoDeGerador(
            nome="Markdown",
            destino=tmp_path / "markdown",
            resultado=Sucesso(valor=None),
        )
        monkeypatch.setattr(
            geracao, "pipeline_executar_geradores", _fake_pipeline_executar([item])
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        geracao.executar_geradores(["Markdown"], banco_analisado, tmp_path)

        assert any(
            "'Markdown': artefato escrito" in chamada["texto"]
            for chamada in interceptar_print
        )


class TestErro:
    """Erro esperado."""

    def test_confirmar_execucao_recusada_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """usuário recusa a confirmação, sai com código 0."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda mensagem: False
        )

        with pytest.raises(SystemExit) as excinfo:
            geracao.confirmar_execucao(["Markdown"], tmp_path)

        assert excinfo.value.code == 0

    def test_executar_geradores_com_falha_sai_com_codigo_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Falha de um Gerador é reportada e sai com código 1."""
        item = ResultadoDeGerador(
            nome="Dbt",
            destino=tmp_path / "dbt",
            resultado=Falha(erro="permissão negada"),
        )
        monkeypatch.setattr(
            geracao, "pipeline_executar_geradores", _fake_pipeline_executar([item])
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        with pytest.raises(SystemExit) as excinfo:
            geracao.executar_geradores(["Dbt"], banco_analisado, tmp_path)

        assert excinfo.value.code == 1
        assert any(
            "Falha em 'Dbt': permissão negada" in chamada["texto"]
            for chamada in interceptar_print
        )


class TestBorda:
    """Bordas."""

    def test_executar_geradores_exibe_cada_item_assim_que_o_pipeline_o_entrega(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Exibição é incremental — 1 chamada de UI por Gerador, na ordem recebida.

        Não em lote ao final: o wrapper reage a cada `ResultadoDeGerador`
        entregue pelo `progresso` do pipeline, não a uma lista já completa.
        """
        itens = [
            ResultadoDeGerador(
                nome="Dbt", destino=tmp_path / "dbt", resultado=Falha(erro="x")
            ),
            ResultadoDeGerador(
                nome="Markdown",
                destino=tmp_path / "markdown",
                resultado=Sucesso(valor=None),
            ),
        ]
        monkeypatch.setattr(
            geracao, "pipeline_executar_geradores", _fake_pipeline_executar(itens)
        )
        eventos: list[str] = []

        def _exibir_espiao(item: ResultadoDeGerador) -> bool:
            eventos.append(item.nome)
            return isinstance(item.resultado, Falha)

        monkeypatch.setattr(geracao, "_exibir_resultado", _exibir_espiao)
        banco_analisado = BancoAnalisado(tabelas=[])

        with pytest.raises(SystemExit):
            geracao.executar_geradores(["Dbt", "Markdown"], banco_analisado, tmp_path)

        assert eventos == ["Dbt", "Markdown"]

    def test_executar_geradores_continua_apos_uma_falha_isolada(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Falha de um Gerador não impede os demais de rodar."""
        itens = [
            ResultadoDeGerador(
                nome="Dbt", destino=tmp_path / "dbt", resultado=Falha(erro="x")
            ),
            ResultadoDeGerador(
                nome="Markdown",
                destino=tmp_path / "markdown",
                resultado=Sucesso(valor=None),
            ),
        ]
        monkeypatch.setattr(
            geracao, "pipeline_executar_geradores", _fake_pipeline_executar(itens)
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        with pytest.raises(SystemExit):
            geracao.executar_geradores(["Dbt", "Markdown"], banco_analisado, tmp_path)

        textos = [chamada["texto"] for chamada in interceptar_print]
        assert any("Falha em 'Dbt'" in texto for texto in textos)
        assert any("'Markdown': artefato escrito" in texto for texto in textos)

    def test_executar_geradores_exibe_avisos_do_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Avisos do ResultadoDeGerador aparecem antes da mensagem de sucesso."""
        item = ResultadoDeGerador(
            nome="Markdown",
            destino=tmp_path / "markdown",
            resultado=Sucesso(
                valor=None,
                avisos=[Aviso(mensagem="coluna sem descrição", origem="Markdown")],
            ),
        )
        monkeypatch.setattr(
            geracao, "pipeline_executar_geradores", _fake_pipeline_executar([item])
        )
        banco_analisado = BancoAnalisado(tabelas=[])

        geracao.executar_geradores(["Markdown"], banco_analisado, tmp_path)

        textos = [chamada["texto"] for chamada in interceptar_print]
        indice_aviso = next(
            i for i, texto in enumerate(textos) if "coluna sem descrição" in texto
        )
        indice_sucesso = next(
            i for i, texto in enumerate(textos) if "artefato escrito" in texto
        )
        assert indice_aviso < indice_sucesso

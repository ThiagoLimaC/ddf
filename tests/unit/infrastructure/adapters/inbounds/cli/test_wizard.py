"""Testes de _sair_se_vazio — os dois pontos de saída antecipada do wizard."""

import logging
from pathlib import Path

import pytest

from ddf.infrastructure.adapters.inbounds.cli.wizard import (
    _configurar_logging,
    _sair_se_vazio,
)


class TestFeliz:
    """Caminho feliz."""

    def test_sair_se_vazio_com_lista_nao_vazia_nao_sai(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Lista com itens não imprime nada nem sai do processo."""
        _sair_se_vazio(["algo"], "Nenhum item processado com sucesso.")

        assert capsys.readouterr().out == ""

    def test_configurar_logging_escreve_log_debug_do_ddf_no_arquivo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Log DEBUG+ vai só pro arquivo `./ddf.log` — nunca pro terminal do usuário.

        Nível padrão do logger raiz é WARNING e nenhum handler é
        configurado por padrão — um `logger.info`/`logger.debug` de um
        Extrator (ex.: streaming ativado) nunca apareceria em lugar nenhum.
        Terminal é território do `prompts.py`, não de log de ferramenta.
        """
        monkeypatch.chdir(tmp_path)
        logger_ddf = logging.getLogger("ddf")
        handlers_originais = list(logger_ddf.handlers)
        nivel_original = logger_ddf.level
        try:
            _configurar_logging()
            logging.getLogger("ddf.teste").debug("mensagem de teste")
            for handler in logger_ddf.handlers:
                handler.flush()

            conteudo_log = (tmp_path / "ddf.log").read_text()
            assert "mensagem de teste" in conteudo_log
            saida = capsys.readouterr()
            assert saida.out == ""
            assert saida.err == ""
        finally:
            for handler in logger_ddf.handlers:
                if handler not in handlers_originais:
                    handler.close()
            logger_ddf.handlers = handlers_originais
            logger_ddf.setLevel(nivel_original)


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


class TestBorda:
    """Bordas."""

    def test_configurar_logging_captura_warnings_de_dependencias_no_arquivo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        r"""`warnings.warn()` de terceiros (ex.: pymysql) vai pro arquivo, não stderr.

        Sem `logging.captureWarnings(True)`, o warning vai cru pro stderr
        (formato `arquivo.py:NNN: UserWarning: mensagem`) — o que intercala
        mal com o redesenho `\r` da barra de progresso e ainda vaza pro
        usuário final. Capturado, ele é roteado pro logger `py.warnings`,
        que grava só no arquivo, no mesmo formatter do resto do ddf.

        Dispara via `logging.getLogger("py.warnings").warning(...)`
        diretamente, não `warnings.warn(...)`: o pytest já embrulha cada
        teste em seu próprio `catch_warnings(record=True)` para relatório,
        o que impede o `showwarning` do `captureWarnings` de ser chamado
        aqui — o que este teste garante é o roteamento/formatter do logger
        de destino, que é o que `_configurar_logging` de fato configura.
        """
        monkeypatch.chdir(tmp_path)
        logger_py_warnings = logging.getLogger("py.warnings")
        handlers_originais = list(logger_py_warnings.handlers)
        logger_ddf = logging.getLogger("ddf")
        handlers_originais_ddf = list(logger_ddf.handlers)
        nivel_original_ddf = logger_ddf.level
        try:
            _configurar_logging()

            assert logger_py_warnings.handlers
            logger_py_warnings.warning("mensagem de teste")
            for handler in logger_py_warnings.handlers:
                handler.flush()

            conteudo_log = (tmp_path / "ddf.log").read_text()
            assert "WARNING py.warnings: mensagem de teste" in conteudo_log
            saida = capsys.readouterr()
            assert saida.out == ""
            assert saida.err == ""
        finally:
            logging.captureWarnings(False)
            for handler in logger_py_warnings.handlers:
                if handler not in handlers_originais:
                    handler.close()
            logger_py_warnings.handlers = handlers_originais
            logger_ddf.handlers = handlers_originais_ddf
            logger_ddf.setLevel(nivel_original_ddf)

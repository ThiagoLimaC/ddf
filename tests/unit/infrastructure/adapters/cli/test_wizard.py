"""Testes de _sair_se_vazio — os dois pontos de saída antecipada do wizard."""

import logging

import pytest

from ddf.infrastructure.adapters.cli.wizard import _configurar_logging, _sair_se_vazio


class TestFeliz:
    """Caminho feliz."""

    def test_sair_se_vazio_com_lista_nao_vazia_nao_sai(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Lista com itens não imprime nada nem sai do processo."""
        _sair_se_vazio(["algo"], "Nenhum item processado com sucesso.")

        assert capsys.readouterr().out == ""

    def test_configurar_logging_torna_log_info_do_ddf_visivel(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Sem isso, `logger.info(...)` de qualquer Adapter some em silêncio.

        Nível padrão do logger raiz é WARNING e nenhum handler é
        configurado por padrão — um `logger.info` de um Extrator (ex.:
        streaming ativado) nunca apareceria em lugar nenhum.
        """
        logger_ddf = logging.getLogger("ddf")
        handlers_originais = list(logger_ddf.handlers)
        nivel_original = logger_ddf.level
        try:
            _configurar_logging()
            logging.getLogger("ddf.teste").info("mensagem de teste")

            assert "mensagem de teste" in capsys.readouterr().err
        finally:
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

"""Testes de executar_com_seguranca()."""

import pytest

from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.comum.seguranca import executar_com_seguranca


class TestFeliz:
    """Caminho feliz."""

    def test_retorna_sucesso_da_funcao_sem_alteracao(self) -> None:
        """Funcao sem exceção passa o Sucesso adiante intacto."""
        resultado = executar_com_seguranca("EstagioFake", lambda: Sucesso(valor=42))

        assert resultado == Sucesso(valor=42)


class TestErro:
    """Erro esperado."""

    def test_excecao_nao_prevista_vira_falha_com_nome_do_estagio_e_tipo(self) -> None:
        """Exception arbitrária vira Falha, nunca propaga crua."""

        def _levanta_erro_de_dtype_inesperado() -> Sucesso[int]:
            raise ValueError("min não suportado para dtype list")

        resultado = executar_com_seguranca(
            "AnalisadorDeMetricasDeColuna", _levanta_erro_de_dtype_inesperado
        )

        assert isinstance(resultado, Falha)
        assert "AnalisadorDeMetricasDeColuna" in resultado.erro
        assert "ValueError" in resultado.erro
        assert "min não suportado para dtype list" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_falha_explicita_da_funcao_passa_direto_sem_reinterpretar(self) -> None:
        """Falha já esperada (domínio) não vira 'Falha inesperada'."""
        resultado: Resultado[int] = executar_com_seguranca(
            "ExtratorPostgres", lambda: Falha("Não foi possível conectar: recusado")
        )

        assert resultado == Falha("Não foi possível conectar: recusado")

    def test_keyboard_interrupt_nao_e_capturado(self) -> None:
        """KeyboardInterrupt/SystemExit não são Exception — propagam normalmente."""

        def _interrompe() -> Sucesso[int]:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            executar_com_seguranca("QualquerEstagio", _interrompe)

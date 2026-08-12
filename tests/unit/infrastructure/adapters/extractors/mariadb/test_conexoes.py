"""Testes de _GerenciadorDeConexoesMariaDB."""

import threading
from unittest.mock import MagicMock

import pymysql
import pytest

from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.mariadb._conexoes import (
    TokenDeReserva,
    _GerenciadorDeConexoesMariaDB,
)


def _gerenciador(max_conexoes: int = 8) -> _GerenciadorDeConexoesMariaDB:
    return _GerenciadorDeConexoesMariaDB(
        host="fake",
        user="user",
        password="senha",
        port=3306,
        max_conexoes=max_conexoes,
        connect_timeout=10,
    )


class TestFeliz:
    """Caminho feliz."""

    def test_construcao_nao_cria_pool_imediatamente(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """__init__ não abre conexão — pool é preguiçoso."""
        _gerenciador()

        pool_classe_fake.assert_not_called()

    def test_conexao_empresta_e_fecha_ao_sair_do_with(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """conexao() empresta do pool e fecha (close) ao sair do with."""
        conexao_fake = MagicMock()
        pool_classe_fake.return_value.connection.return_value = conexao_fake
        gerenciador = _gerenciador()

        with gerenciador.conexao() as resultado:
            assert resultado == Sucesso(conexao_fake)

        conexao_fake.close.assert_called_once()

    def test_reservar_atingindo_minimo_devolve_token_com_n_reservado(self) -> None:
        """reservar() com folga suficiente devolve TokenDeReserva.n == maximo."""
        gerenciador = _gerenciador()

        token = gerenciador.reservar(maximo=4)

        assert token == TokenDeReserva(n=4)

    def test_liberar_devolve_permits_reservados_ao_semaforo(self) -> None:
        """liberar(token) devolve exatamente token.n permits ao semáforo."""
        gerenciador = _gerenciador(max_conexoes=2)
        token = gerenciador.reservar(maximo=2)
        assert token is not None

        gerenciador.liberar(token)

        # Os 2 permits devolvidos permitem reservar de novo até o máximo.
        segundo_token = gerenciador.reservar(maximo=2)
        assert segundo_token == TokenDeReserva(n=2)


class TestErro:
    """Erro esperado."""

    def test_falha_ao_criar_pool_vira_falha_legivel(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """OperationalError na criação do pool vira Falha, não exceção crua."""
        pool_classe_fake.side_effect = pymysql.err.OperationalError(
            "connection refused"
        )
        gerenciador = _gerenciador()

        with gerenciador.conexao() as resultado:
            assert isinstance(resultado, Falha)
            assert "Não foi possível conectar" in resultado.erro

    def test_falha_ao_obter_conexao_do_pool_ja_criado_vira_falha(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """OperationalError em connection() (pool já existe) vira Falha."""
        pool_classe_fake.return_value.connection.side_effect = (
            pymysql.err.OperationalError("connection refused")
        )
        gerenciador = _gerenciador()

        with gerenciador.conexao() as resultado:
            assert isinstance(resultado, Falha)
            assert "Não foi possível conectar" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_reservar_abaixo_do_minimo_devolve_none(self) -> None:
        """Pedir menos que o mínimo não reserva nada — devolve None, não token vazio."""
        gerenciador = _gerenciador()

        token = gerenciador.reservar(maximo=1, minimo=2)

        assert token is None

    def test_conexao_libera_semaforo_mesmo_com_excecao_no_corpo(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """Exceção não tratada dentro do with ainda libera o semáforo."""
        conexao_fake = MagicMock()
        pool_classe_fake.return_value.connection.return_value = conexao_fake
        gerenciador = _gerenciador(max_conexoes=1)

        with pytest.raises(ValueError, match="erro no corpo"):
            with gerenciador.conexao():
                raise ValueError("erro no corpo")

        # Semáforo (1 permit) livre de novo — release aconteceu no finally.
        assert gerenciador._semaforo.acquire(timeout=0.2) is True
        gerenciador._semaforo.release()

    def test_primeiro_uso_concorrente_cria_pool_uma_unica_vez(
        self, pool_classe_fake: MagicMock
    ) -> None:
        """Chamadas concorrentes no 1º uso criam o pool uma única vez.

        Sem lock em _obter_pool, duas threads poderiam ver self._pool is
        None ao mesmo tempo e construir o pool duas vezes — exatamente o
        cenário que o lock existe para prevenir.
        """
        primeira_thread_entrou = threading.Event()
        pode_prosseguir = threading.Event()

        def construir_pool_lento(**_kwargs: object) -> MagicMock:
            if not primeira_thread_entrou.is_set():
                primeira_thread_entrou.set()
                pode_prosseguir.wait(timeout=1)
            return MagicMock()

        pool_classe_fake.side_effect = construir_pool_lento
        gerenciador = _gerenciador(max_conexoes=10)

        thread_lenta = threading.Thread(target=gerenciador._obter_pool)
        thread_lenta.start()
        assert primeira_thread_entrou.wait(timeout=1) is True

        resultado_concorrente = gerenciador._obter_pool()
        pode_prosseguir.set()
        thread_lenta.join(timeout=1)

        assert pool_classe_fake.call_count == 1
        assert isinstance(resultado_concorrente, Sucesso)

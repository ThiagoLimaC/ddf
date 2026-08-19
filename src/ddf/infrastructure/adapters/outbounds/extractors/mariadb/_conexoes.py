"""Gerencia pool, semáforo e locks de concorrência do ExtratorMariaDB.

Objeto composto pelo Extrator (não herdado, não uma função solta recebendo a
instância inteira do Extrator como parâmetro) — a dependência é
estritamente unidirecional: este módulo não importa `ExtratorMariaDB` de
volta, então não há ciclo de import. Os locks/semáforo internos nunca saem
daqui; quem usa este objeto só vê `conexao()`/`reservar()`/`liberar()`.

Sem `conexao_ja_reservada()` (ao contrário do gêmeo Postgres,
`_GerenciadorDeConexoesPostgres`): nenhuma leitura paralela do MariaDB toma
emprestado do `PooledDB` — `connectorx` abre conexão própria via DSN, sem
conexão líder nem snapshot (ver docstring de
`ExtratorMariaDB._ler_tabela_em_paralelo`). Forçar esse método aqui só por
simetria criaria API morta.

O que fica fora, de propósito: cache de metadados de schema
(`_cache_schemas`/`_lock_cache_schemas`) é um eixo de mudança diferente —
muda por schema/dialeto de metadado, não por infraestrutura de pool — e
continua em `ExtratorMariaDB`. Toda lógica de dialeto/extração também
continua lá; só troca a chamada de conexão por uma chamada a este objeto.
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pymysql
from dbutils.pooled_db import PooledDB

from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.outbounds.extractors.comum.leitura_paralela_intra_tabela import (  # noqa: E501
    MINIMO_CONEXOES_PARALELISMO,
    liberar_conexoes,
    reservar_conexoes,
)


@dataclass(frozen=True)
class TokenDeReserva:
    """Prova de que `reservar()` já reservou `n` permits do semáforo.

    `liberar()` exige este token como argumento — chamar sem ter reservado
    antes vira erro de tipo, não um lapso de leitura de docstring. Mesmo
    contrato do gêmeo Postgres (`_conexoes.TokenDeReserva`).
    """

    n: int


class _GerenciadorDeConexoesMariaDB:
    """Empresta conexões de um `PooledDB`, sob um semáforo.

    Criado sem parâmetro de estado compartilhado com o Extrator — só os
    parâmetros de conexão. O pool só é criado no primeiro uso.
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int,
        max_conexoes: int,
        connect_timeout: int,
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._port = port
        self._max_conexoes = max_conexoes
        self._connect_timeout = connect_timeout
        self._pool: PooledDB | None = None
        self._semaforo = threading.Semaphore(max_conexoes)
        self._lock_pool = threading.Lock()
        self._lock_reserva_paralelismo = threading.Lock()

    def _obter_pool(self) -> Resultado[PooledDB]:
        """Cria o pool sob demanda, pra falha de conexão virar Falha, não exceção."""
        if self._pool is None:
            with self._lock_pool:
                if self._pool is None:
                    try:
                        self._pool = PooledDB(
                            creator=pymysql,
                            mincached=1,
                            maxcached=self._max_conexoes,
                            maxconnections=self._max_conexoes,
                            blocking=True,
                            host=self._host,
                            port=self._port,
                            user=self._user,
                            password=self._password,
                            autocommit=True,
                            connect_timeout=self._connect_timeout,
                        )
                    except pymysql.err.OperationalError as erro:
                        return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    @contextmanager
    def conexao(self) -> Generator[Resultado[Any], None, None]:
        """Empresta uma conexão do pool, com devolução (`close`) garantida.

        `PooledDB` foi criado com `blocking=True` (`_obter_pool`), então
        `pool.connection()` já bloqueia internamente quando o pool está
        saturado, em vez de levantar erro — mas isso sozinho não basta
        desde que o paralelismo intra-tabela passou a reservar conexões via
        `reservar()`: as conexões que o `connectorx` abre por conta própria
        (fora deste `PooledDB`) também precisam contar contra o mesmo
        orçamento `max_conexoes`, senão o total real de conexões no
        servidor pode passar do configurado. `self._semaforo` (mesmo
        padrão do `_GerenciadorDeConexoesPostgres`) cobre as duas fontes.

        `yield`a um `Falha` cedo, sem entrar no `try`/`finally` de conexão,
        quando o pool não pode ser obtido ou `pool.connection()` falha —
        nesses casos não há conexão nem posse do semáforo a devolver. Tipo
        `Any` porque `dbutils.pooled_db` não tem stubs
        (`ignore_missing_imports` em `pyproject.toml`).
        """
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            yield resultado_pool
            return
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.connection()
        except pymysql.err.OperationalError as erro:
            self._semaforo.release()
            yield Falha(f"Não foi possível conectar: {erro}")
            return
        try:
            yield Sucesso(conexao)
        finally:
            conexao.close()
            self._semaforo.release()

    def reservar(
        self, maximo: int, minimo: int = MINIMO_CONEXOES_PARALELISMO
    ) -> TokenDeReserva | None:
        """Reserva conexões pra leitura paralela; ver `reservar_conexoes`.

        Returns:
            `None` quando a reserva não atingiu `minimo` (chamador cai no
            caminho sequencial; não há nada a liberar). Caso contrário, o
            `TokenDeReserva` — `token.n` é quantas conexões foram
            efetivamente reservadas (entre `minimo` e `maximo`) — exigido
            por `liberar()`.
        """
        n = reservar_conexoes(
            self._semaforo, self._lock_reserva_paralelismo, maximo, minimo
        )
        if n < MINIMO_CONEXOES_PARALELISMO:
            return None
        return TokenDeReserva(n=n)

    def liberar(self, token: TokenDeReserva) -> None:
        """Libera as conexões reservadas por uma chamada anterior a `reservar`."""
        liberar_conexoes(self._semaforo, token.n)

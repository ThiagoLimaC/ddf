"""Gerencia pool, semáforo e locks de concorrência do ExtratorPostgres.

Objeto composto pelo Extrator (não herdado, não uma função solta recebendo a
instância inteira do Extrator como parâmetro) — a dependência é
estritamente unidirecional: este módulo não importa `ExtratorPostgres` de
volta, então não há ciclo de import. Os locks/semáforo internos nunca saem
daqui; quem usa este objeto só vê `conexao()`/`conexao_ja_reservada()`/
`reservar()`/`liberar()`.

O que fica fora, de propósito: cache de metadados de schema
(`_cache_schemas`/`_lock_cache_schemas`) é um eixo de mudança diferente —
muda por schema/dialeto de metadado, não por infraestrutura de pool — e
continua em `ExtratorPostgres`. Toda lógica de dialeto/extração (leitura
paralela via connectorx, sondas de largura/blocos) também continua lá; só
troca a chamada de conexão por uma chamada a este objeto.
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from psycopg2 import OperationalError
from psycopg2.extensions import connection as conexao_postgres
from psycopg2.pool import ThreadedConnectionPool

from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.outbounds.extractors.comum.leitura_paralela_intra_tabela import (  # noqa: E501
    MINIMO_CONEXOES_PARALELISMO,
    liberar_conexoes,
    reservar_conexoes,
)


@dataclass(frozen=True)
class TokenDeReserva:
    """Prova de que `reservar()` já reservou `n` permits do semáforo.

    `conexao_ja_reservada()` exige este token como argumento — chamar sem
    ter reservado antes vira erro de tipo (nenhum `TokenDeReserva` em mãos
    pra passar), não um lapso de leitura de docstring. Existe só pra isso;
    `n` não é consultado por quem chama.
    """

    n: int


class _GerenciadorDeConexoesPostgres:
    """Empresta conexões de um `ThreadedConnectionPool`, sob um semáforo.

    Criado sem parâmetro de estado compartilhado com o Extrator — só os
    parâmetros de conexão. O pool só é criado no primeiro uso.
    """

    def __init__(
        self, dsn: str, max_conexoes: int, connect_timeout: int
    ) -> None:
        self._dsn = dsn
        self._max_conexoes = max_conexoes
        self._connect_timeout = connect_timeout
        self._pool: ThreadedConnectionPool | None = None
        self._semaforo = threading.Semaphore(max_conexoes)
        self._lock_pool = threading.Lock()
        self._lock_reserva_paralelismo = threading.Lock()

    def _obter_pool(self) -> Resultado[ThreadedConnectionPool]:
        """Cria o pool sob demanda, pra falha de conexão virar Falha, não exceção."""
        if self._pool is None:
            with self._lock_pool:
                if self._pool is None:
                    try:
                        self._pool = ThreadedConnectionPool(
                            minconn=1,
                            maxconn=self._max_conexoes,
                            dsn=self._dsn,
                            connect_timeout=self._connect_timeout,
                        )
                    except OperationalError as erro:
                        return Falha(f"Não foi possível conectar: {erro}")
        return Sucesso(self._pool)

    @contextmanager
    def conexao(
        self, autocommit: bool = True
    ) -> Generator[Resultado[conexao_postgres], None, None]:
        """Empresta uma conexão do pool, sob o semáforo, com release garantido.

        `yield`a um `Falha` cedo, sem entrar no bloco `try`/`finally` de
        conexão, quando o próprio pool não pode ser obtido ou o
        `getconn()` falha — nesses casos não há conexão nem posse do
        semáforo a devolver. Quando a conexão é obtida com sucesso, o
        `finally` garante `putconn` + liberação do semáforo mesmo se o
        corpo do `with` levantar uma exceção não tratada.

        Args:
            autocommit: `False` sustenta uma transação aberta na conexão
                emprestada — obrigatório para cursor nomeado (streaming).
                Quem pede `autocommit=False` é responsável por chamar
                `conexao.commit()` no caminho de sucesso, antes do `with`
                terminar; no caminho de erro, o `rollback()` automático do
                `ThreadedConnectionPool.putconn` cobre a limpeza — sem
                vazamento de estado entre quem pegar a conexão emprestada
                depois, só a duração da transação fica maior enquanto
                durar o streaming.
        """
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            yield resultado_pool
            return
        pool = resultado_pool.valor
        self._semaforo.acquire()
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            self._semaforo.release()
            yield Falha(f"Não foi possível conectar: {erro}")
            return
        try:
            conexao.autocommit = autocommit
            yield Sucesso(conexao)
        finally:
            pool.putconn(conexao)
            self._semaforo.release()

    @contextmanager
    def conexao_ja_reservada(
        self, token: TokenDeReserva, autocommit: bool = True
    ) -> Generator[Resultado[conexao_postgres], None, None]:
        """Empresta uma conexão do pool sem tocar no semáforo.

        Uso restrito à leitura paralela intra-tabela: o orçamento de
        conexões já foi reservado antes (via `reservar()`, que devolveu o
        `token` exigido aqui) — adquirir o semáforo de novo aqui
        dessincronizaria a contagem do quanto está realmente em uso. Exigir
        `token` por assinatura (não só por docstring) torna chamar isto sem
        ter reservado antes um erro de tipo, não um lapso de leitura: não há
        `TokenDeReserva` em mãos pra passar se `reservar()` nunca rodou.
        Mesmo formato de `conexao`, só sem o `acquire`/`release`. `token` não
        é lido — existe só como prova de posse na assinatura; `reservar()`/
        `liberar()` já tocam o semáforo.
        """
        resultado_pool = self._obter_pool()
        if isinstance(resultado_pool, Falha):
            yield resultado_pool
            return
        pool = resultado_pool.valor
        try:
            conexao = pool.getconn()
        except OperationalError as erro:
            yield Falha(f"Não foi possível conectar: {erro}")
            return
        try:
            conexao.autocommit = autocommit
            yield Sucesso(conexao)
        finally:
            pool.putconn(conexao)

    def reservar(
        self, maximo: int, minimo: int = MINIMO_CONEXOES_PARALELISMO
    ) -> TokenDeReserva | None:
        """Reserva conexões pra leitura paralela; ver `reservar_conexoes`.

        Returns:
            `None` quando a reserva não atingiu `minimo` (chamador cai no
            caminho sequencial; não há nada a liberar). Caso contrário, o
            `TokenDeReserva` — `token.n` é quantas conexões foram
            efetivamente reservadas (entre `minimo` e `maximo`) — exigido
            por `conexao_ja_reservada()`/`liberar()`.
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

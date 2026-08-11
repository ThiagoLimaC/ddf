"""Testes de deve_paralelizar_leitura/reservar_conexoes/liberar_conexoes."""

import threading

from ddf.infrastructure.adapters.extractors.comum.leitura_paralela_intra_tabela import (
    MINIMO_CONEXOES_PARALELISMO,
    deve_paralelizar_leitura,
    liberar_conexoes,
    reservar_conexoes,
)


class TestFeliz:
    """Caminho feliz."""

    def test_nao_paraleliza_tabela_pequena(self) -> None:
        """Tabela bem abaixo dos dois limiares não justifica paralelismo."""
        resultado = deve_paralelizar_leitura(
            total_linhas=1_000, largura_media_bytes=100
        )

        assert resultado is False

    def test_paraleliza_por_limiar_de_linhas(self) -> None:
        """Muitas linhas estreitas ainda cruzam o limiar de linhas sozinho."""
        resultado = deve_paralelizar_leitura(
            total_linhas=1_000_000, largura_media_bytes=10
        )

        assert resultado is True

    def test_paraleliza_por_limiar_de_bytes(self) -> None:
        """Poucas linhas bem largas cruzam o limiar de bytes sozinho."""
        resultado = deve_paralelizar_leitura(
            total_linhas=10_000, largura_media_bytes=100_000
        )

        assert resultado is True

    def test_reserva_o_maximo_pedido_quando_disponivel(self) -> None:
        """Semáforo com folga de sobra reserva exatamente `maximo`."""
        semaforo = threading.Semaphore(8)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=4)

        assert n == 4

    def test_libera_conexoes_devolve_permits_ao_semaforo(self) -> None:
        """Depois de liberar, o semáforo volta a aceitar o total original."""
        semaforo = threading.Semaphore(8)
        lock = threading.Lock()
        n = reservar_conexoes(semaforo, lock, maximo=4)

        liberar_conexoes(semaforo, n)

        # Se os 4 permits voltaram, dá pra adquirir os 8 de novo.
        adquiridos = sum(1 for _ in range(8) if semaforo.acquire(blocking=False))
        assert adquiridos == 8


class TestBorda:
    """Casos de borda."""

    def test_reduz_progressivamente_ate_o_minimo_disponivel(self) -> None:
        """Só 3 permits livres, pediu 5 -> reserva os 3, respeitando o mínimo."""
        semaforo = threading.Semaphore(3)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=5, minimo=2)

        assert n == 3

    def test_nao_reserva_nada_abaixo_do_minimo_disponivel(self) -> None:
        """Só 1 permit livre, mínimo é 2 -> não reserva nada, devolve o permit."""
        semaforo = threading.Semaphore(1)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=5, minimo=2)

        assert n == 0
        # O único permit não ficou preso na tentativa fracassada.
        assert semaforo.acquire(blocking=False) is True

    def test_maximo_igual_ao_minimo_reserva_exatamente_isso(self) -> None:
        """`maximo == minimo` não é tratado como caso especial."""
        semaforo = threading.Semaphore(2)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=2, minimo=2)

        assert n == 2

    def test_default_de_minimo_e_o_da_constante_publica(self) -> None:
        """O default de `minimo` é `MINIMO_CONEXOES_PARALELISMO`, não outro valor."""
        semaforo = threading.Semaphore(MINIMO_CONEXOES_PARALELISMO - 1)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=MINIMO_CONEXOES_PARALELISMO + 1)

        assert n == 0

    def test_reserva_concorrente_nunca_deixa_permits_negativos(self) -> None:
        """N threads competindo pelo mesmo orçamento nunca sobre-reservam.

        Reproduz o cenário que motivou o achado bloqueante do arquiteto:
        várias tabelas grandes tentando reservar conexão ao mesmo tempo.
        Com reserva atômica sob lock, a soma de tudo que foi efetivamente
        reservado nunca deveria exceder a capacidade total do semáforo.
        """
        capacidade = 8
        semaforo = threading.Semaphore(capacidade)
        lock = threading.Lock()
        reservados: list[int] = []
        trava_resultado = threading.Lock()

        def _tentar_reservar() -> None:
            n = reservar_conexoes(semaforo, lock, maximo=3, minimo=2)
            with trava_resultado:
                reservados.append(n)

        threads = [threading.Thread(target=_tentar_reservar) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(reservados) <= capacidade


class TestErro:
    """Erro esperado / uso indevido."""

    def test_maximo_menor_que_minimo_nao_reserva_nada(self) -> None:
        """`maximo < minimo` é rejeitado antes de tocar no semáforo."""
        semaforo = threading.Semaphore(10)
        lock = threading.Lock()

        n = reservar_conexoes(semaforo, lock, maximo=1, minimo=2)

        assert n == 0
        assert semaforo.acquire(blocking=False) is True

    def test_liberar_zero_conexoes_nao_altera_o_semaforo(self) -> None:
        """`liberar_conexoes(semaforo, 0)` é um no-op seguro."""
        semaforo = threading.Semaphore(1)
        semaforo.acquire()

        liberar_conexoes(semaforo, 0)

        assert semaforo.acquire(blocking=False) is False

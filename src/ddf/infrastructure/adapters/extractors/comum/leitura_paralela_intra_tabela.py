"""Decide e reserva orçamento pra paralelismo intra-tabela, sem orquestrar a leitura.

`deve_paralelizar_leitura`/`reservar_conexoes`/`liberar_conexoes` formam um
único fluxo de decisão (mesmo padrão de `ler_amostra_em_lotes.py`: se
paraleliza, com quantas conexões, como devolver o orçamento) — não uma
orquestração genérica de partição→leitura→merge. `ExtratorPostgres` e
`ExtratorMariaDB` têm ciclos de vida de conexão (snapshot líder vs.
transações independentes) e formatos de partição (`ctid` físico vs. faixa
de PK) divergentes demais pra caber atrás de um único laço compartilhado —
cada um mantém seu próprio laço de orquestração dentro de `extrair_tabela`,
reaproveitando só as funções puras daqui.
"""

import threading

_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA = 500_000
_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA = 500_000_000
"""Candidatos iniciais, não calibrados — mesmo tratamento dos limiares de
streaming em `deve_usar_streaming`. Mais altos que os de streaming de
propósito: paralelismo intra-tabela paga o custo de várias conexões e
transações simultâneas, só compensa em tabelas bem maiores que o piso onde
o streaming já compensa sozinho."""

MINIMO_CONEXOES_PARALELISMO = 2
"""Mínimo de conexões (1 líder/coordenadora + 1 worker) pra o paralelismo
intra-tabela valer a pena — abaixo disso, quem chama cai no caminho
sequencial/streaming já existente, sem tentar paralelizar."""


def deve_paralelizar_leitura(total_linhas: int, largura_media_bytes: int) -> bool:
    """Decide se a tabela justifica o custo de ler em paralelo com M conexões.

    Dois critérios (linhas OU bytes), mesmo raciocínio de
    `deve_usar_streaming`: um limiar de bytes sozinho depende da estimativa
    de largura média, que cai num fallback conservador quando a tabela
    nunca foi analisada; um limiar de linhas sozinho não distingue 1M
    linhas estreitas de 1M linhas largas. Cada critério cobre o ponto cego
    do outro.

    Args:
        total_linhas: total de linhas estimado da tabela (catálogo).
        largura_media_bytes: estimativa de largura média de linha.
    """
    tamanho_estimado_bytes = total_linhas * largura_media_bytes
    return (
        total_linhas > _LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA
        or tamanho_estimado_bytes > _LIMIAR_BYTES_PARALELISMO_INTRA_TABELA
    )


def reservar_conexoes(
    semaforo: threading.Semaphore,
    lock_reserva: threading.Lock,
    maximo: int,
    minimo: int = MINIMO_CONEXOES_PARALELISMO,
) -> int:
    """Reserva atomicamente entre `minimo` e `maximo` permits do semáforo.

    Aquisições independentes (uma conexão líder bloqueada esperando workers
    adquirirem do mesmo semáforo) são hold-and-wait clássico — com várias
    tabelas grandes concorrentes, todos os permits podem ficar presos em
    líderes bloqueados, cada um esperando por permits que outro líder está
    segurando. `lock_reserva` evita isso serializando toda tentativa de
    reserva — só uma thread por vez fica no meio da dança de "adquirir N,
    conferir se deu certo, devolver se não deu" — então nenhuma thread
    nunca fica de posse parcial de permits enquanto espera pelo resto.
    Cada tentativa usa só `acquire(blocking=False)`: se não conseguir
    `tentativa` permits, devolve os que conseguiu e tenta um valor menor,
    até `minimo`; nunca bloqueia esperando permits que outra tabela possa
    estar segurando.

    Args:
        semaforo: semáforo de conexões do Extrator (mesmo usado por
            `_conexao()` pra chamadas sequenciais normais).
        lock_reserva: lock dedicado à serialização de reservas — não é o
            mesmo lock usado por outro propósito do Extrator (ex.: cache de
            schema), pra não serializar coisas sem relação entre si.
        maximo: teto de conexões que esta tabela tentaria reservar
            (tipicamente `max_conexoes_por_tabela`).
        minimo: menor quantidade que ainda vale a pena paralelizar —
            abaixo disso, retorna 0 (sinal pro chamador cair no caminho
            sequencial).

    Returns:
        Quantas conexões foram efetivamente reservadas (entre `minimo` e
        `maximo`), ou `0` se nem `minimo` estava disponível agora.
    """
    if maximo < minimo:
        return 0
    with lock_reserva:
        for tentativa in range(maximo, minimo - 1, -1):
            adquiridos = 0
            while adquiridos < tentativa and semaforo.acquire(blocking=False):
                adquiridos += 1
            if adquiridos == tentativa:
                return tentativa
            for _ in range(adquiridos):
                semaforo.release()
    return 0


def liberar_conexoes(semaforo: threading.Semaphore, n: int) -> None:
    """Libera `n` permits reservados por uma chamada anterior a `reservar_conexoes`.

    Args:
        semaforo: o mesmo semáforo passado a `reservar_conexoes`.
        n: quantidade a liberar — o valor devolvido por `reservar_conexoes`.
    """
    for _ in range(n):
        semaforo.release()

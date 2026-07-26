"""Helper agnóstico de fonte pra sempre ter um seed concreto de amostragem."""

import random

_SEED_MAXIMO = 2**31 - 1


def seed_efetivo(seed: int | None) -> int:
    """Devolve `seed` se informado, senão gera um novo.

    Reprodutibilidade nunca é opt-in silencioso: mesmo sem `seed` do
    usuário, cada Extrator passa um valor concreto para
    `REPEATABLE`/`RAND` do próprio dialeto e registra o valor gerado em
    `MetadadosDeAmostra` — sem isso, a amostra não seria reproduzível a
    partir do artefato, mesmo que o usuário quisesse reproduzi-la depois.

    Args:
        seed: valor informado pelo usuário, ou None se não informado.
    """
    if seed is not None:
        return seed
    return random.randint(0, _SEED_MAXIMO)

"""Tipo compartilhado para avisos não fatais emitidos por um Estagio."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Aviso:
    """Representa um aviso não fatal emitido durante a execução de um Estagio.

    `agrupado` é um hint pro CLI (`avisos.exibir_avisos`), não uma garantia
    de domínio: `True` (default) — mensagem curta, esperada aos montes
    (ex.: uma falha por tabela) — agrupa por origem/tipo, mostra as
    primeiras `_LIMITE_AVISOS_DETALHADOS` e colapsa o resto. `False` — já é
    o resultado final de uma agregação feita por quem emitiu o Aviso (ex.:
    "N de M tabela(s)..."), sempre única — exibida como linha solta
    "▲ mensagem", sem cabeçalho de origem nem reagrupamento por cima.
    """

    mensagem: str
    origem: str
    agrupado: bool = True

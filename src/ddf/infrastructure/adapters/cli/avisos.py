"""Exibição de Avisos e saída padronizada em Falha, compartilhadas pelo wizard."""

import re
import sys
from typing import TypeVar

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado

T = TypeVar("T")

_LIMITE_AVISOS_DETALHADOS = 3

_PADRAO_IDENTIFICADOR = re.compile(r"'[^']*'")
_PADRAO_NUMERO = re.compile(r"\d+")


def ou_sair(resultado: Resultado[T]) -> T:
    """Exibe os avisos e devolve o valor de Sucesso; sai com código 1 em Falha."""
    exibir_avisos(resultado.avisos)
    if isinstance(resultado, Falha):
        print(f"Erro: {resultado.erro}")
        sys.exit(1)
    return resultado.valor


def _tipo_de_aviso(mensagem: str) -> str:
    """Normaliza uma mensagem de Aviso para agrupar por "tipo", não por texto exato.

    Troca identificadores entre aspas simples (nome de tabela/coluna/caminho)
    e números soltos (contagens, tamanhos de amostra) por um placeholder —
    "Amostra pequena (N=5) em 'x.y.z'" e "Amostra pequena (N=8) em 'a.b.c'"
    viram o mesmo "tipo", mesmo com texto literal diferente. Heurística, não
    garantia: mensagens genuinamente diferentes que só variam em número/aspas
    por coincidência colapsariam juntas — aceitável para exibição no
    terminal, nunca usado para decisão de negócio.

    Args:
        mensagem: texto original do Aviso.
    """
    sem_identificadores = _PADRAO_IDENTIFICADOR.sub("'…'", mensagem)
    return _PADRAO_NUMERO.sub("#", sem_identificadores)


def exibir_avisos(avisos: list[Aviso]) -> None:
    """Exibe avisos agrupados por origem e por "tipo" — nunca esconde um tipo diferente.

    Mensagens do mesmo "tipo" (mesma forma, só o identificador muda — ex.:
    skeleton criado para tabelas diferentes) mostram as primeiras
    `_LIMITE_AVISOS_DETALHADOS` ocorrências na íntegra (identificador real
    incluído), para o usuário ver exemplos concretos; a partir daí, colapsam
    numa linha condensada com a contagem total do tipo.

    Args:
        avisos: avisos acumulados na etapa, na ordem em que ocorreram.
    """
    if not avisos:
        return

    print()
    grupos_por_origem: dict[str, dict[str, list[str]]] = {}
    ordem_origem: list[str] = []
    for aviso in avisos:
        if aviso.origem not in grupos_por_origem:
            ordem_origem.append(aviso.origem)
            grupos_por_origem[aviso.origem] = {}
        tipo = _tipo_de_aviso(aviso.mensagem)
        grupos_por_origem[aviso.origem].setdefault(tipo, []).append(aviso.mensagem)

    for origem in ordem_origem:
        grupos = grupos_por_origem[origem]
        total = sum(len(mensagens) for mensagens in grupos.values())
        print(f"  [{origem}] {total} aviso(s):")
        for tipo, mensagens in grupos.items():
            for mensagem in mensagens[:_LIMITE_AVISOS_DETALHADOS]:
                print(f"    - {mensagem}")
            if len(mensagens) > _LIMITE_AVISOS_DETALHADOS:
                print(f"    - {tipo} (x{len(mensagens)})")

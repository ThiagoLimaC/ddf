"""Núcleo de chamada de Port da etapa de geração — sem UI."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from ddf.domain.model.analysis import BancoAnalisado
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.resultado import Resultado
from ddf.pipeline.comum.seguranca import executar_com_seguranca

_LIMITE_PALAVRA = re.compile(r"(.)([A-Z][a-z]+)")
_LIMITE_SIGLA = re.compile(r"([a-z0-9])([A-Z])")


def _slugificar(nome: str) -> str:
    """Converte um nome de registro CamelCase em snake_case pra nome de pasta.

    Genérico — não depende de conhecer os nomes dos Geradores nativos de
    antemão, ao contrário de um dicionário fixo por nome. "ContextoDeIA"
    vira "contexto_de_ia", "Markdown" vira "markdown", sem exceção
    cadastrada à parte para nenhum dos dois.
    """
    com_separador_de_palavra = _LIMITE_PALAVRA.sub(r"\1_\2", nome)
    com_separador_de_sigla = _LIMITE_SIGLA.sub(r"\1_\2", com_separador_de_palavra)
    return com_separador_de_sigla.lower()


class ResultadoDeGerador(NamedTuple):
    """Resultado da execução de um Gerador — nome, destino e Resultado."""

    nome: str
    destino: Path
    resultado: Resultado[None]


def executar_geradores(
    nomes_geradores: list[str],
    geradores_registrados: dict[str, Gerador],
    banco_analisado: BancoAnalisado,
    destino: Path,
    progresso: Callable[[ResultadoDeGerador], None] | None = None,
) -> list[ResultadoDeGerador]:
    """Único ponto que chama cada Gerador selecionado, protegido por rede de segurança.

    Cada Gerador escreve na sua própria subpasta (`destino/<slug>`), mesmo
    quando só um é escolhido.

    Args:
        nomes_geradores: nomes dos Geradores escolhidos pelo usuário.
        geradores_registrados: Geradores disponíveis, por nome de registro.
        banco_analisado: banco curado com as métricas já calculadas.
        destino: diretório raiz onde os artefatos são escritos.
        progresso: chamado uma vez por Gerador, logo após ele terminar —
            preserva exibição incremental (aviso/sucesso/falha por
            Gerador) para quem chama, em vez de só saber de tudo depois
            que o loop inteiro termina.

    Returns:
        Um `ResultadoDeGerador` por Gerador executado, na ordem de
        `nomes_geradores`.
    """
    resultados: list[ResultadoDeGerador] = []
    for nome in nomes_geradores:
        gerador = geradores_registrados[nome]
        destino_gerador = destino / _slugificar(nome)
        resultado = executar_com_seguranca(
            nome, lambda: gerador(banco_analisado, destino_gerador)
        )
        item = ResultadoDeGerador(
            nome=nome, destino=destino_gerador, resultado=resultado
        )
        resultados.append(item)
        if progresso is not None:
            progresso(item)
    return resultados

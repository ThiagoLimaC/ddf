"""Núcleo de chamada de Port da etapa de extração — sem UI."""

from collections.abc import Callable

from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado

_ORIGEM = "Extracao"


def testar_conexao(extrator: Extrator) -> Resultado[list[str]]:
    """Único ponto que chama Extrator.listar_escopos().

    Args:
        extrator: Extrator recém-construído, ainda não testado.

    Returns:
        Sucesso com os escopos disponíveis, ou Falha com o erro de conexão.
    """
    return extrator.listar_escopos()


def listar_pares(
    extrator: Extrator, escopos: list[str]
) -> tuple[list[tuple[str, str]], list[Aviso]]:
    """Agrega Extrator.listar_tabelas() por escopo, com sucesso parcial.

    Falha ao listar um escopo vira Aviso e não impede a listagem dos
    demais. Não exibe nada — quem chama decide quando/como exibir os
    avisos devolvidos.

    Args:
        extrator: Extrator já conectado.
        escopos: escopos escolhidos pelo usuário.

    Returns:
        Tupla com os pares (escopo, tabela) agregados dos escopos que
        responderam com sucesso, e um Aviso por escopo que falhou.
    """
    pares: list[tuple[str, str]] = []
    avisos: list[Aviso] = []
    for escopo in escopos:
        resultado = extrator.listar_tabelas(escopo)
        if isinstance(resultado, Falha):
            avisos.append(
                Aviso(
                    mensagem=(
                        f"Falha ao listar tabelas de '{escopo}': {resultado.erro}"
                    ),
                    origem=_ORIGEM,
                )
            )
            continue
        pares.extend(resultado.valor)
    return pares, avisos


def extrair_tabelas(
    orquestrador: OrquestradorDeTabelas,
    extrator: Extrator,
    pares: list[tuple[str, str]],
    progresso: Callable[[str], None] | None = None,
) -> Resultado[list[TabelaExtraida]]:
    """Único ponto que chama OrquestradorDeTabelas.extrair().

    Args:
        orquestrador: coordena a extração em paralelo.
        extrator: fonte de onde as tabelas são extraídas.
        pares: (escopo, tabela) das tabelas a extrair.
        progresso: chamado a cada tabela extraída, se informado.

    Returns:
        Sucesso com as tabelas extraídas (falha individual vira Aviso),
        ou Falha se o lote inteiro não puder ser processado.
    """
    return orquestrador.extrair(pares, extrator, progresso=progresso)

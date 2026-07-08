"""Validação pura de produz/requer entre Analisadores e Geradores selecionados."""

from ddf.domain.model.analysis import TipoDeMetrica
from ddf.domain.ports.analisador import Analisador
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


def validar_dependencias(
    analisadores: list[Analisador],
    geradores: list[Gerador],
) -> Resultado[list[Analisador]]:
    """Valida que todos os requer de Analisadores e Geradores estão satisfeitos.

    Em sucesso, devolve os Analisadores reordenados topologicamente por
    produz/requer — a ordem de seleção do usuário não determina a ordem de
    execução, só o conjunto selecionado.
<<<<<<< HEAD

    Args:
        analisadores: Analisadores selecionados pelo usuário.
        geradores: Geradores selecionados pelo usuário.

    Returns:
        Sucesso com os Analisadores reordenados topologicamente, ou Falha
        com a descrição da dependência ausente ou do ciclo detectado.
=======
>>>>>>> origin/main
    """
    produzido_por = _mapear_produtores(analisadores)

    ausentes = _dependencias_ausentes(analisadores, geradores, produzido_por)
    if ausentes:
        return Falha("Dependências não satisfeitas: " + "; ".join(ausentes) + ".")

    ordenados = _ordenar_topologicamente(analisadores, produzido_por)
    if isinstance(ordenados, str):
        return Falha(ordenados)

    return Sucesso(valor=ordenados)


def _mapear_produtores(
    analisadores: list[Analisador],
) -> dict[TipoDeMetrica, Analisador]:
<<<<<<< HEAD
    """Mapeia cada métrica produzida ao Analisador selecionado que a produz.

    Args:
        analisadores: Analisadores selecionados pelo usuário.

    Returns:
        Dicionário de TipoDeMetrica para o Analisador que a produz.
    """
=======
    """Mapeia cada métrica produzida ao Analisador selecionado que a produz."""
>>>>>>> origin/main
    return {
        metrica: analisador
        for analisador in analisadores
        for metrica in analisador.produz
    }


def _dependencias_ausentes(
    analisadores: list[Analisador],
    geradores: list[Gerador],
    produzido_por: dict[TipoDeMetrica, Analisador],
) -> list[str]:
<<<<<<< HEAD
    """Lista, em texto, cada requer não satisfeito pelo conjunto selecionado.

    Args:
        analisadores: Analisadores selecionados pelo usuário.
        geradores: Geradores selecionados pelo usuário.
        produzido_por: Mapa de TipoDeMetrica para o Analisador que a produz.

    Returns:
        Lista de mensagens, uma por dependência não satisfeita.
    """
=======
    """Lista, em texto, cada requer não satisfeito pelo conjunto selecionado."""
>>>>>>> origin/main
    ausentes: list[str] = []
    for analisador in analisadores:
        for metrica in analisador.requer:
            if metrica not in produzido_por:
                ausentes.append(
                    f"{type(analisador).__name__} requer {metrica.__name__}, "
                    "que nenhum Analisador selecionado produz"
                )
    for gerador in geradores:
        for metrica in gerador.requer:
            if metrica not in produzido_por:
                ausentes.append(
                    f"{type(gerador).__name__} requer {metrica.__name__}, "
                    "que nenhum Analisador selecionado produz"
                )
    return ausentes


def _ordenar_topologicamente(
    analisadores: list[Analisador],
    produzido_por: dict[TipoDeMetrica, Analisador],
) -> list[Analisador] | str:
<<<<<<< HEAD
    """Ordena Analisadores por dependência ou devolve mensagem de ciclo detectado.

    Args:
        analisadores: Analisadores selecionados pelo usuário.
        produzido_por: Mapa de TipoDeMetrica para o Analisador que a produz.

    Returns:
        Lista de Analisadores ordenada topologicamente por produz/requer,
        ou uma mensagem de texto descrevendo o ciclo detectado.
    """
=======
    """Ordena Analisadores por dependência ou devolve mensagem de ciclo detectado."""
>>>>>>> origin/main
    dependencias: dict[int, set[int]] = {
        id(analisador): {id(produzido_por[metrica]) for metrica in analisador.requer}
        for analisador in analisadores
    }

    ordenados: list[Analisador] = []
    resolvidos: set[int] = set()
    restantes = list(analisadores)

    while restantes:
        prontos = [a for a in restantes if dependencias[id(a)] <= resolvidos]
        if not prontos:
            nomes = ", ".join(type(a).__name__ for a in restantes)
            return f"Ciclo de dependências detectado entre: {nomes}."
        for analisador in prontos:
            ordenados.append(analisador)
            resolvidos.add(id(analisador))
        restantes = [a for a in restantes if id(a) not in resolvidos]

    return ordenados

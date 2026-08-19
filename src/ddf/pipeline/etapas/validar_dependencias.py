"""Validação pura de produz/requer entre Analisadores e Geradores selecionados."""

from ddf.domain.model.analysis import TipoDeMetrica
from ddf.domain.ports.analisador import Analisador
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


def validar_dependencias(
    analisadores: dict[str, Analisador],
    geradores: dict[str, Gerador],
) -> Resultado[list[Analisador]]:
    """Valida que todos os requer de Analisadores e Geradores estão satisfeitos.

    Em sucesso, devolve os Analisadores reordenados topologicamente por
    produz/requer — a ordem de seleção do usuário não determina a ordem de
    execução, só o conjunto selecionado.

    Recebe dicts (nome de registro -> instância), não listas soltas, para
    que mensagens de erro citem o rótulo exibido no menu do wizard (ex.:
    "Dbt") em vez do nome da classe Python (ex.: "GeradorDbt").

    Args:
        analisadores: Analisadores selecionados pelo usuário, por nome de
            registro.
        geradores: Geradores selecionados pelo usuário, por nome de registro.

    Returns:
        Sucesso com os Analisadores reordenados topologicamente, ou Falha
        com a descrição da dependência ausente ou do ciclo detectado.
    """
    rotulos: dict[int, str] = {
        id(instancia): nome
        for registro in (analisadores, geradores)
        for nome, instancia in registro.items()
    }
    lista_analisadores = list(analisadores.values())
    lista_geradores = list(geradores.values())

    produzido_por = _mapear_produtores(lista_analisadores)

    ausentes = _dependencias_ausentes(
        lista_analisadores, lista_geradores, produzido_por, rotulos
    )
    if ausentes:
        return Falha("Dependências não satisfeitas: " + "; ".join(ausentes) + ".")

    ordenados = _ordenar_topologicamente(lista_analisadores, produzido_por, rotulos)
    if isinstance(ordenados, str):
        return Falha(ordenados)

    return Sucesso(valor=ordenados)


def _rotulo(instancia: Analisador | Gerador, rotulos: dict[int, str]) -> str:
    """Devolve o nome de registro da instância, com o nome da classe como fallback."""
    return rotulos.get(id(instancia), type(instancia).__name__)


def _mapear_produtores(
    analisadores: list[Analisador],
) -> dict[TipoDeMetrica, Analisador]:
    """Mapeia cada métrica produzida ao Analisador selecionado que a produz.

    Args:
        analisadores: Analisadores selecionados pelo usuário.

    Returns:
        Dicionário de TipoDeMetrica para o Analisador que a produz.
    """
    produzido_por: dict[TipoDeMetrica, Analisador] = {}
    for analisador in analisadores:
        for metrica in analisador.produz:
            produzido_por[metrica] = analisador
    return produzido_por


def _dependencias_ausentes(
    analisadores: list[Analisador],
    geradores: list[Gerador],
    produzido_por: dict[TipoDeMetrica, Analisador],
    rotulos: dict[int, str],
) -> list[str]:
    """Lista, em texto, cada requer não satisfeito pelo conjunto selecionado.

    Args:
        analisadores: Analisadores selecionados pelo usuário.
        geradores: Geradores selecionados pelo usuário.
        produzido_por: Mapa de TipoDeMetrica para o Analisador que a produz.
        rotulos: Mapa de id(instância) para o nome exibido no menu do wizard.

    Returns:
        Lista de mensagens, uma por dependência não satisfeita.
    """
    ausentes: list[str] = []
    for analisador in analisadores:
        for metrica in analisador.requer:
            if metrica not in produzido_por:
                ausentes.append(
                    f"{_rotulo(analisador, rotulos)} requer {metrica.__name__}, "
                    "que nenhum Analisador selecionado produz"
                )
    for gerador in geradores:
        for metrica in gerador.requer:
            if metrica not in produzido_por:
                ausentes.append(
                    f"{_rotulo(gerador, rotulos)} requer {metrica.__name__}, "
                    "que nenhum Analisador selecionado produz"
                )
    return ausentes


def _ordenar_topologicamente(
    analisadores: list[Analisador],
    produzido_por: dict[TipoDeMetrica, Analisador],
    rotulos: dict[int, str],
) -> list[Analisador] | str:
    """Ordena Analisadores por dependência ou devolve mensagem de ciclo detectado.

    Args:
        analisadores: Analisadores selecionados pelo usuário.
        produzido_por: Mapa de TipoDeMetrica para o Analisador que a produz.
        rotulos: Mapa de id(instância) para o nome exibido no menu do wizard.

    Returns:
        Lista de Analisadores ordenada topologicamente por produz/requer,
        ou uma mensagem de texto descrevendo o ciclo detectado.
    """
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
            nomes = ", ".join(_rotulo(a, rotulos) for a in restantes)
            return f"Ciclo de dependências detectado entre: {nomes}."
        for analisador in prontos:
            ordenados.append(analisador)
            resolvidos.add(id(analisador))
        restantes = [a for a in restantes if id(a) not in resolvidos]

    return ordenados

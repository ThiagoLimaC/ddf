"""Núcleo de composição da etapa de análise — sem UI."""

from ddf.domain.model.analysis import BancoAnalisado, iniciar_contexto
from ddf.domain.model.curation import BancoCurado
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.comum.compor import compor


def analisar(
    analisadores_ordenados: list[Analisador], banco_curado: BancoCurado
) -> Resultado[BancoAnalisado]:
    """Único ponto que monta o ContextoDeAnalise e executa compor().

    Args:
        analisadores_ordenados: Analisadores já ordenados topologicamente
            por produz/requer.
        banco_curado: banco curado a partir do qual o ContextoDeAnalise
            é montado.

    Returns:
        Sucesso com o BancoAnalisado e os avisos acumulados de todos os
        Analisadores, ou Falha no primeiro Analisador que falhar.
    """
    contexto = iniciar_contexto(banco_curado)
    resultado = compor(*analisadores_ordenados)(contexto)
    if isinstance(resultado, Falha):
        return resultado
    return Sucesso(valor=resultado.valor.analisado, avisos=resultado.avisos)

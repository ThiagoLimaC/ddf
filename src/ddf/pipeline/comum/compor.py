"""Composição sequencial de Estagios homogêneos."""

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline.comum.estagio import Estagio, Saida
from ddf.pipeline.comum.seguranca import executar_com_seguranca


def _nome_do_estagio(estagio: object) -> str:
    """Deriva um nome legível do Estagio, pra mensagem de Falha e log interno.

    Args:
        estagio: instância de Adapter (a maioria dos casos reais) ou função
            solta que implementa o Protocol Estagio.

    Returns:
        `__name__` do próprio objeto se for uma função, senão o nome da
        classe da instância (ex.: "AnalisadorDeMetricasDeColuna").
    """
    return getattr(estagio, "__name__", type(estagio).__name__)


def compor(*estagios: Estagio[Saida, Saida]) -> Estagio[Saida, Saida]:
    """Compõe estágios em sequência, acumulando avisos e parando no 1º erro."""

    def _executar(entrada: Saida) -> Sucesso[Saida] | Falha:
        valor = entrada
        avisos: list[Aviso] = []
        for estagio in estagios:
            resultado = executar_com_seguranca(
                _nome_do_estagio(estagio), lambda: estagio(valor)
            )
            if isinstance(resultado, Falha):
                return Falha(erro=resultado.erro, avisos=avisos + resultado.avisos)
            avisos.extend(resultado.avisos)
            valor = resultado.valor
        return Sucesso(valor=valor, avisos=avisos)

    return _executar

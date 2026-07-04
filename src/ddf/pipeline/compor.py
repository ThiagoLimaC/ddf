"""Composição sequencial de Estagios homogêneos."""

from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline.estagio import Estagio, Saida


def compor(*estagios: Estagio[Saida, Saida]) -> Estagio[Saida, Saida]:
    """Compõe estágios em sequência, acumulando avisos e parando no 1º erro."""

    def _executar(entrada: Saida) -> Sucesso[Saida] | Falha:
        valor = entrada
        avisos: list[Aviso] = []
        for estagio in estagios:
            resultado = estagio(valor)
            if isinstance(resultado, Falha):
                return Falha(erro=resultado.erro, avisos=avisos + resultado.avisos)
            avisos.extend(resultado.avisos)
            valor = resultado.valor
        return Sucesso(valor=valor, avisos=avisos)

    return _executar

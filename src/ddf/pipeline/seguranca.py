"""Rede de segurança contra exceções não previstas por nenhum Adapter."""

import logging
from collections.abc import Callable
from typing import TypeVar

from ddf.domain.shared.resultado import Falha, Resultado

T = TypeVar("T")

_logger = logging.getLogger(__name__)


def executar_com_seguranca(
    nome_estagio: str, funcao: Callable[[], Resultado[T]]
) -> Resultado[T]:
    """Converte qualquer Exception não antecipada de `funcao` em Falha.

    Rede de segurança para exceções que nenhum Adapter previu — não
    substitui a conversão de exceções esperadas e específicas em Falha com
    mensagem de domínio já feita por cada Adapter (ex.: `OperationalError`
    de conexão recusada vira `Falha("Não foi possível conectar...")` antes
    de chegar aqui). Captura `Exception`, não `BaseException`: não
    intercepta `KeyboardInterrupt`/`SystemExit`. A exceção original vai pro
    log interno (`logging.exception`, com traceback) para a causa raiz
    continuar visível à equipe — só a mensagem resumida chega no `Resultado`
    devolvido ao chamador.

    Args:
        nome_estagio: identificador do Estagio ou ponto de chamada, usado
            na mensagem de `Falha` e no log interno (ex.: nome da classe do
            Analisador, "Extrator", "GeradorDbt").
        funcao: chamada a proteger, sem argumentos — o chamador encapsula
            os argumentos reais via closure/lambda.

    Returns:
        O `Resultado` de `funcao` se ela não levantar exceção; `Falha` com
        o nome do Estagio e o tipo da exceção original se levantar.
    """
    try:
        return funcao()
    except Exception as erro:
        _logger.exception("Falha não tratada em '%s'", nome_estagio)
        return Falha(
            f"Falha inesperada em '{nome_estagio}': {type(erro).__name__}: {erro}"
        )

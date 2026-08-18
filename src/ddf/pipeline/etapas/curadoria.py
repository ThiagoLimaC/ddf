"""Núcleo de chamada de Port da etapa de curadoria — sem UI."""

from collections.abc import Callable

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.resultado import Resultado
from ddf.pipeline.comum.estagio import Estagio


def aplicar_sobrescritas_em_lote(
    orquestrador: OrquestradorDeTabelas,
    sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    tabelas: list[TabelaExtraida],
    progresso: Callable[[str], None] | None = None,
) -> Resultado[BancoCurado]:
    """Único ponto que chama OrquestradorDeTabelas.aplicar_sobrescritas().

    Reusada pelos dois wrappers de UI de curadoria — o que gera/atualiza
    skeletons (descarta o BancoCurado retornado) e o que aplica a
    sobrescrita já editada pelo usuário (usa o BancoCurado retornado) —
    ambos chamam esta mesma Port com os mesmos argumentos.

    Args:
        orquestrador: coordena a aplicação da sobrescrita em paralelo.
        sobrescrita: traduz cada TabelaExtraida em TabelaCurada.
        tabelas: tabelas extraídas a curar.
        progresso: chamado a cada tabela curada, se informado.

    Returns:
        Sucesso com o BancoCurado (falha individual vira Aviso), ou
        Falha se o lote inteiro não puder ser processado.
    """
    return orquestrador.aplicar_sobrescritas(
        tabelas, sobrescrita, progresso=progresso
    )

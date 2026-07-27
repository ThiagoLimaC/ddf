"""Etapas 6-8 do wizard: skeletons de sobrescrita, pausa e curadoria manual."""

from pathlib import Path

from ddf.domain.model.curation import BancoCurado
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import ou_sair
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)


def curar(
    orquestrador: OrquestradorDeTabelas,
    diretorio_overrides: Path,
    tabelas: list[TabelaExtraida],
) -> SobrescritaDeTabela:
    """Etapas 6-7: gera/atualiza skeletons e pausa para curadoria manual."""
    sobrescrita = SobrescritaDeTabela(diretorio_overrides)
    _gerar_skeletons(orquestrador, sobrescrita, tabelas)

    prompts.pausar(
        f"Edite os YAMLs de overrides em '{diretorio_overrides.resolve()}' e "
        "aperte uma tecla para continuar..."
    )
    return sobrescrita


def _gerar_skeletons(
    orquestrador: OrquestradorDeTabelas,
    sobrescrita: SobrescritaDeTabela,
    tabelas: list[TabelaExtraida],
) -> None:
    """Etapa 6: gera/atualiza os skeletons de sobrescrita em disco.

    O resultado (TabelaCurada de rascunho) é descartado aqui de propósito —
    só o efeito colateral em disco e os Avisos importam nesta passada; a
    curadoria de verdade vem da 2ª passada, em `aplicar_sobrescritas`, após
    o usuário editar os YAMLs.
    """
    progresso, _definir_total = prompts.progresso_paralelo(
        "Gerando skeletons de sobrescrita...", len(tabelas)
    )
    resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita, progresso)
    print()
    ou_sair(resultado)

    criados_ou_atualizados = len(resultado.avisos)
    preservados = len(tabelas) - criados_ou_atualizados
    print(
        f"{criados_ou_atualizados} skeleton(s) criado(s)/atualizado(s), "
        f"{preservados} preservado(s) sem mudança."
    )


def aplicar_sobrescritas(
    orquestrador: OrquestradorDeTabelas,
    sobrescrita: SobrescritaDeTabela,
    tabelas: list[TabelaExtraida],
) -> BancoCurado:
    """Etapa 8: reaplica a sobrescrita (já editada) em paralelo, gera o BancoCurado."""
    progresso, _definir_total = prompts.progresso_paralelo(
        "Aplicando sobrescritas...", len(tabelas)
    )
    resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita, progresso)
    print()
    return ou_sair(resultado)

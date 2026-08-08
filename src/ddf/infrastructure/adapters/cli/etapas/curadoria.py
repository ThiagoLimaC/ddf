"""Etapas 6-8 do wizard: skeletons de sobrescrita, pausa e curadoria manual."""

import sys
from pathlib import Path

from ddf.domain.model.curation import BancoCurado
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.resultado import Falha
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

    Não usa `avisos.ou_sair` (que exibiria um Aviso por tabela criada/
    atualizada) — com dezenas ou centenas de tabelas, essa lista vira ruído;
    o efeito colateral em disco já é o que importa, resumido numa única
    linha informativa em vez de um Aviso por arquivo.
    """
    with prompts.ampulheta("Gerando skeletons..."):
        resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita)
    print()
    if isinstance(resultado, Falha):
        print(f"Erro: {resultado.erro}")
        sys.exit(1)

    criados_ou_atualizados = len(resultado.avisos)
    preservados = len(tabelas) - criados_ou_atualizados
    mensagem = (
        f"{criados_ou_atualizados} skeleton(s) criado(s)/atualizado(s), "
        f"{preservados} preservado(s) sem mudança."
    )
    if criados_ou_atualizados:
        mensagem += " Preencha a curadoria e reexecute."
    print(mensagem)


def aplicar_sobrescritas(
    orquestrador: OrquestradorDeTabelas,
    sobrescrita: SobrescritaDeTabela,
    tabelas: list[TabelaExtraida],
) -> BancoCurado:
    """Etapa 8: reaplica a sobrescrita (já editada) em paralelo, gera o BancoCurado."""
    with prompts.ampulheta("Aplicando sobrescritas..."):
        resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita)
    print()
    return ou_sair(resultado)

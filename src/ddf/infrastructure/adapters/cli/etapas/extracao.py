"""Etapas 1-5 do wizard: amostragem, conexão, escopos e extração das tabelas."""

import sys
import time

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import ou_sair
from ddf.infrastructure.adapters.cli.registro.estrategias import (
    ESTRATEGIAS_REGISTRADAS,
)
from ddf.infrastructure.adapters.cli.registro.extratores import (
    EXTRATORES_REGISTRADOS,
)

_MAXIMO_TENTATIVAS_CONEXAO = 3


def configurar_amostragem() -> ConfiguracaoDeExtracao:
    """Etapa 1: escolhe a estratégia de amostragem, monta a ConfiguracaoDeExtracao.

    `EstrategiaDeAmostragem` é um Port — `PercentualDeLinhas` e
    `TabelaInteira` (issue #76) já provam que o registro cresce sem
    precisar editar este wizard.
    """
    nome_estrategia = prompts.selecionar(
        "Qual estratégia de amostragem?", list(ESTRATEGIAS_REGISTRADAS.keys())
    )
    estrategia = ESTRATEGIAS_REGISTRADAS[nome_estrategia].construir()
    return ConfiguracaoDeExtracao(estrategia=estrategia)


def conectar(configuracao: ConfiguracaoDeExtracao) -> tuple[Extrator, list[str]]:
    """Etapas 2-3: escolhe a fonte, constrói o Extrator e testa a conexão.

    Reaproveita o Resultado de `listar_escopos()` como sonda de
    conectividade — a etapa 4 (escolher escopos) usa a mesma lista, sem uma
    2ª chamada de rede.
    """
    nome_fonte = prompts.selecionar(
        "Qual fonte?", list(EXTRATORES_REGISTRADOS.keys())
    )
    extrator = EXTRATORES_REGISTRADOS[nome_fonte].construir(configuracao)
    escopos = _testar_conexao(extrator)
    return extrator, escopos


def _testar_conexao(extrator: Extrator) -> list[str]:
    """Etapa 3: testa a conexão via listar_escopos(), com retry manual até 3x.

    Nunca faz retry automático com a mesma credencial — em caso de senha
    errada contra um banco real, retry cego pode contribuir para travar a
    conta por excesso de tentativas. Quem decide tentar de novo é o usuário.
    """
    tentativa = 1
    while True:
        with prompts.ampulheta("Testando conexão..."):
            resultado = extrator.listar_escopos()
        print()
        if not isinstance(resultado, Falha):
            prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)
            return resultado.valor

        print(
            f"Falha ao conectar (tentativa {tentativa}/"
            f"{_MAXIMO_TENTATIVAS_CONEXAO}): {resultado.erro}"
        )
        if tentativa >= _MAXIMO_TENTATIVAS_CONEXAO:
            sys.exit(1)
        if prompts.selecionar("O que fazer?", ["Tentar novamente", "Sair"]) == "Sair":
            sys.exit(1)
        tentativa += 1


def _contar_tabelas(extrator: Extrator, escopos: list[str]) -> int | None:
    """Pré-lista as tabelas dos escopos só para saber o total esperado no progresso.

    Falha em listar algum escopo aqui não é fatal — `orquestrador.extrair`
    trata isso de verdade (vira Aviso); aqui só degrada para progresso sem
    total (contagem corrida), sem duplicar tratamento de erro.

    Args:
        extrator: Extrator já conectado.
        escopos: escopos escolhidos pelo usuário.
    """
    total = 0
    for escopo in escopos:
        resultado = extrator.listar_tabelas(escopo)
        if isinstance(resultado, Falha):
            return None
        total += len(resultado.valor)
    return total


def extrair(
    orquestrador: OrquestradorDeTabelas, extrator: Extrator, escopos: list[str]
) -> list[TabelaExtraida]:
    """Etapa 5: extrai, em paralelo, todas as tabelas dos escopos escolhidos."""
    total = _contar_tabelas(extrator, escopos)
    progresso = prompts.progresso_paralelo("Extraindo tabelas...", total)
    inicio = time.monotonic()
    resultado = orquestrador.extrair(escopos, extrator, progresso=progresso)
    print()
    print(f"⏱️  duração: {time.monotonic() - inicio:.0f}s")
    return ou_sair(resultado)

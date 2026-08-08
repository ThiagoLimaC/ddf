"""Registro de Estratégias de amostragem disponíveis para o wizard da CLI."""

import sys
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.extractors.estrategias.amostragem_por_faixa import (
    AmostragemPorFaixa,
)
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira import (
    TabelaInteira,
)


@dataclass(frozen=True)
class EstrategiaRegistrada:
    """Uma EstrategiaDeAmostragem registrada, junto da função que a constrói."""

    construir: Callable[[], EstrategiaDeAmostragem]


ESTRATEGIAS_REGISTRADAS: dict[str, EstrategiaRegistrada] = {}


def registrar_estrategia(
    nome: str,
    construir: Callable[[], EstrategiaDeAmostragem],
    registro: dict[str, EstrategiaRegistrada] = ESTRATEGIAS_REGISTRADAS,
) -> None:
    """Registra uma nova Estratégia de amostragem no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: Identificador da estratégia exibido ao usuário no wizard.
        construir: Função que constrói uma instância da estratégia,
            perguntando interativamente os parâmetros que ela precisa.
        registro: Dicionário onde a estratégia é registrada. Usa
            ESTRATEGIAS_REGISTRADAS por padrão.
    """
    registrar_ou_falhar(
        nome,
        "Estratégia",
        EstrategiaRegistrada(construir=construir),
        registro,
        feminino=True,
    )


def _construir_percentual_de_linhas() -> EstrategiaDeAmostragem:
    """Pergunta percentual e seed opcional, monta o PercentualDeLinhas.

    Percentual fora de (0, 100] levanta ValidationError (Pydantic, mensagem
    em inglês) dentro de AmostragemProbabilistica — capturado aqui pra sair
    com mensagem em português, mesmo padrão de `ou_sair` (avisos.py).
    """
    percentual = prompts.numero(
        "Percentual de amostragem (0-100]:", float, default="10"
    )
    seed = prompts.numero_opcional(
        "Seed para reprodutibilidade (opcional, deixe em branco para aleatório):",
        int,
    )
    try:
        return PercentualDeLinhas(percentual=percentual, seed=seed)
    except ValidationError:
        prompts.imprimir_destacado(
            f"Erro: percentual deve estar em (0, 100] ({percentual}).", prompts.COR_ERRO
        )
        sys.exit(1)


def _construir_tabela_inteira() -> EstrategiaDeAmostragem:
    """Confirma o custo de memória e monta TabelaInteira.

    Sem percentual pra limitar o tamanho (ao contrário de
    `PercentualDeLinhas`, cujo default 10 protege por acidente), essa
    estratégia carrega a tabela inteira em memória de uma vez — risco real
    de OOM em tabelas muito grandes. A confirmação existe pra essa escolha
    nunca ser silenciosa.
    """
    prosseguir = prompts.confirmar(
        "Tabela inteira carrega tudo em memória, sem limite. Continuar?",
        default=True,
    )
    if not prosseguir:
        sys.exit(0)
    return TabelaInteira()


def _construir_amostragem_por_faixa() -> EstrategiaDeAmostragem:
    """Confirma o trade-off de viés e monta AmostragemPorFaixa.

    Mais barata que `PercentualDeLinhas` (custo ~proporcional ao
    percentual, não ao total de linhas), mas amostra por faixa/bloco em
    vez de linha — pode distorcer métricas em tabelas com padrão de
    inserção em lote. A confirmação existe pra essa troca nunca ser
    silenciosa, mesmo padrão de `_construir_tabela_inteira`.
    """
    prosseguir = prompts.confirmar(
        "Amostragem por faixa é mais rápida em tabelas grandes, mas "
        "amostra por faixa/bloco, não por linha — pode distorcer métricas "
        "em tabelas alimentadas em lote ou particionadas por tempo. "
        "Continuar?",
        default=True,
    )
    if not prosseguir:
        sys.exit(0)
    percentual = prompts.numero(
        "Percentual de amostragem (0-100]:", float, default="10"
    )
    seed = prompts.numero_opcional(
        "Seed para reprodutibilidade (opcional, deixe em branco para aleatório):",
        int,
    )
    try:
        return AmostragemPorFaixa(percentual=percentual, seed=seed)
    except ValidationError:
        prompts.imprimir_destacado(
            f"Erro: percentual deve estar em (0, 100] ({percentual}).", prompts.COR_ERRO
        )
        sys.exit(1)


registrar_estrategia("Percentual de linhas", _construir_percentual_de_linhas)
registrar_estrategia("Tabela inteira", _construir_tabela_inteira)
registrar_estrategia("Amostragem por faixa", _construir_amostragem_por_faixa)

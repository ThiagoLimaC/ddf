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
    em inglês) dentro de AmostragemProbabilistica — capturado aqui pra
    reperguntar em português, via `perguntar_repetir` (mesmo padrão de
    `escolher_multiplos`: uma resposta bem formada que ainda fere uma regra
    de negócio pede confirmação antes de sair, não sai direto).

    Avisa uma vez, aqui na escolha da estratégia, que ela sempre varre a
    tabela inteira (custo estrutural, igual nos dois Extratores) — não por
    tabela extraída (`construir_metadados_de_amostra`), pra não repetir o
    mesmo fato dezenas/centenas de vezes numa extração real. Informativo
    (não bloqueia com `confirmar`): o default de 10% já protege contra o
    pior caso por acidente.
    """
    while True:
        percentual = prompts.numero(
            "Percentual de amostragem (0-100):", float, default="10"
        )
        seed = prompts.numero_opcional(
            "Seed para reprodutibilidade (opcional, deixe em branco para usar "
            "o padrão fixo do ddf):",
            int,
        )
        try:
            estrategia = PercentualDeLinhas(percentual=percentual, seed=seed)
            break
        except ValidationError:
            prompts.perguntar_repetir(
                f"percentual deve estar em (0, 100] ({percentual})."
            )
    print()
    prompts.imprimir_destacado(
        "▲ Amostragem por percentual varre a tabela inteira, independente "
        "do percentual escolhido.",
        prompts.COR_AVISO,
    )
    return estrategia


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
    """Pergunta percentual e seed opcional, monta a AmostragemPorFaixa e avisa o viés.

    Mais barata que `PercentualDeLinhas` (custo ~proporcional ao
    percentual, não ao total de linhas), mas amostra por faixa/bloco em
    vez de linha — pode distorcer métricas em tabelas com padrão de
    inserção em lote.

    Aviso informativo (não bloqueia com `confirmar`) depois de montar a
    estratégia, substituindo o `Aviso` que `construir_metadados_de_amostra`
    emitia por tabela pra RequisicaoPorFaixa. Motor-agnóstico de propósito:
    o Extrator concreto ainda não foi escolhido/conectado quando o wizard
    pergunta a estratégia, então cita só o efeito (viés de cluster), não o
    mecanismo específico por motor (TABLESAMPLE SYSTEM no Postgres, faixas
    de PK no MariaDB).

    Percentual fora de (0, 100] repergunta via `perguntar_repetir`, mesmo
    tratamento de `_construir_percentual_de_linhas`.
    """
    while True:
        percentual = prompts.numero(
            "Percentual de amostragem (0-100]:", float, default="10"
        )
        seed = prompts.numero_opcional(
            "Seed para reprodutibilidade (opcional, deixe em branco para usar "
            "o padrão fixo do ddf):",
            int,
        )
        try:
            estrategia = AmostragemPorFaixa(percentual=percentual, seed=seed)
            break
        except ValidationError:
            prompts.perguntar_repetir(
                f"percentual deve estar em (0, 100] ({percentual})."
            )
    print()
    prompts.imprimir_destacado(
        "▲ Amostragem por faixa amostra por faixa/bloco, não por linha — "
        "pode distorcer métricas em tabelas alimentadas em lote ou "
        "particionadas por tempo.",
        prompts.COR_AVISO,
    )
    return estrategia


registrar_estrategia("Percentual de linhas", _construir_percentual_de_linhas)
registrar_estrategia("Tabela inteira", _construir_tabela_inteira)
registrar_estrategia("Amostragem por faixa", _construir_amostragem_por_faixa)

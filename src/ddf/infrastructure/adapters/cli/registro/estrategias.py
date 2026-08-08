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

    Avisa uma vez, aqui na escolha da estratégia, que ela sempre varre a
    tabela inteira (custo estrutural, igual nos dois Extratores) — não mais
    um `Aviso` por tabela extraída (`construir_metadados_de_amostra`, antes
    da #116): o fato não muda de tabela pra tabela, então repeti-lo dezenas/
    centenas de vezes numa extração real só era ruído. Mesma família de
    aviso pontual de `_construir_tabela_inteira`/`_construir_amostragem_
    por_faixa`, só que informativo (não bloqueia com `confirmar`) — o
    default de 10% já protege contra o pior caso por acidente. `print()`
    antes do aviso segue o mesmo padrão do resto do módulo `cli/` (ex.:
    `extracao.py::_testar_conexao`, `curadoria.py::_gerar_skeletons`): uma
    linha em branco separando uma mensagem de status da pergunta/ação que
    veio antes dela.
    """
    percentual = prompts.numero(
        "Percentual de amostragem (0-100]:", float, default="10"
    )
    seed = prompts.numero_opcional(
        "Seed para reprodutibilidade (opcional, deixe em branco para aleatório):",
        int,
    )
    try:
        estrategia = PercentualDeLinhas(percentual=percentual, seed=seed)
    except ValidationError:
        prompts.imprimir_destacado(
            f"Erro: percentual deve estar em (0, 100] ({percentual}).", prompts.COR_ERRO
        )
        sys.exit(1)
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

    Padronizado com `_construir_percentual_de_linhas` (#116): aviso
    informativo (`imprimir_destacado`, não bloqueia com `confirmar`) depois
    de montar a estratégia — não mais uma pergunta de sim/não antes das
    perguntas de percentual/seed. Esse aviso também é o que substitui o
    `Aviso` que `construir_metadados_de_amostra` emitia por tabela pra
    RequisicaoPorFaixa (antes da #116): mesmo texto estrutural repetido
    dezenas/centenas de vezes numa extração real (só o nome da tabela
    mudava) — igual ao caso já resolvido de `PercentualDeLinhas`. É
    motor-agnóstico de propósito: o Extrator concreto ainda não foi
    escolhido/conectado quando o wizard pergunta a estratégia, então não dá
    pra citar o mecanismo específico (TABLESAMPLE SYSTEM no Postgres,
    faixas de PK no MariaDB) aqui — só o efeito (viés de cluster), que é o
    que importa pra decisão do usuário.
    """
    percentual = prompts.numero(
        "Percentual de amostragem (0-100]:", float, default="10"
    )
    seed = prompts.numero_opcional(
        "Seed para reprodutibilidade (opcional, deixe em branco para aleatório):",
        int,
    )
    try:
        estrategia = AmostragemPorFaixa(percentual=percentual, seed=seed)
    except ValidationError:
        prompts.imprimir_destacado(
            f"Erro: percentual deve estar em (0, 100] ({percentual}).", prompts.COR_ERRO
        )
        sys.exit(1)
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

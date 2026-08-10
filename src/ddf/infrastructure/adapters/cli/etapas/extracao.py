"""Etapas 1-5 do wizard: conexão, escopos, amostragem e extração das tabelas."""

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


def conectar() -> tuple[Extrator, ConfiguracaoDeExtracao, list[str]]:
    """Etapas 1-2: escolhe a fonte, constrói o Extrator sem estratégia, testa conexão.

    A estratégia de amostragem só é escolhida depois, em
    `configurar_amostragem` — já com fonte conectada e escopos conhecidos —
    por isso `ConfiguracaoDeExtracao` é construída aqui com `estrategia=None`
    e devolvida junto, para ser preenchida antes da extração de fato.

    Reaproveita o Resultado de `listar_escopos()` como sonda de
    conectividade — a etapa 3 (escolher escopos) usa a mesma lista, sem uma
    2ª chamada de rede.
    """
    nome_fonte = prompts.selecionar(
        "Qual fonte?", list(EXTRATORES_REGISTRADOS.keys())
    )
    configuracao = ConfiguracaoDeExtracao()
    extrator, escopos = _testar_conexao(nome_fonte, configuracao)
    return extrator, configuracao, escopos


def configurar_amostragem(configuracao: ConfiguracaoDeExtracao) -> None:
    """Etapa 4: escolhe a estratégia de amostragem, atribuindo à configuração já em uso.

    `configuracao` é o mesmo objeto já guardado pelo Extrator construído em
    `conectar` — atribuir `estrategia` aqui é o que ele lê ao extrair.

    `EstrategiaDeAmostragem` é um Port — `PercentualDeLinhas` e
    `TabelaInteira` já provam que o registro cresce sem precisar editar
    este wizard.
    """
    nome_estrategia = prompts.selecionar(
        "Qual estratégia de amostragem?", list(ESTRATEGIAS_REGISTRADAS.keys())
    )
    configuracao.estrategia = ESTRATEGIAS_REGISTRADAS[nome_estrategia].construir()


def _testar_conexao(
    nome_fonte: str, configuracao: ConfiguracaoDeExtracao
) -> tuple[Extrator, list[str]]:
    """Etapa 3: constrói o Extrator e testa a conexão, com retry manual até 3x.

    Reconstrói o Extrator a cada tentativa — pedindo host/porta/credenciais
    de novo — em vez de reusar a mesma instância com os mesmos parâmetros já
    errados: se a falha foi por um dado digitado errado (ex.: senha), retry
    cego contra a mesma credencial nunca teria sucesso, só desperdiçaria
    tentativas. Nunca insiste sozinho — quem decide tentar de novo (e o que
    muda nos parâmetros) é o usuário.
    """
    tentativa = 1
    while True:
        extrator = EXTRATORES_REGISTRADOS[nome_fonte].construir(configuracao)
        with prompts.ampulheta("Testando conexão..."):
            resultado = extrator.listar_escopos()
        print()
        if not isinstance(resultado, Falha):
            prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)
            return extrator, resultado.valor

        prompts.imprimir_destacado(
            f"Falha ao conectar (tentativa {tentativa}/"
            f"{_MAXIMO_TENTATIVAS_CONEXAO}): {resultado.erro}",
            prompts.COR_ERRO,
        )
        if tentativa >= _MAXIMO_TENTATIVAS_CONEXAO:
            sys.exit(1)
        if not prompts.confirmar("Tentar novamente?"):
            sys.exit(1)
        tentativa += 1


def extrair(
    orquestrador: OrquestradorDeTabelas, extrator: Extrator, escopos: list[str]
) -> list[TabelaExtraida]:
    """Etapa 5: extrai, em paralelo, todas as tabelas dos escopos escolhidos.

    Total exibido na barra de progresso vem do próprio `orquestrador.extrair`
    (`ao_conhecer_total`), assim que ele termina de listar as tabelas
    internamente — sem uma 2ª listagem só para saber a contagem.
    """
    progresso, definir_total = prompts.progresso_paralelo("Tabelas extraídas")
    inicio = time.monotonic()
    resultado = orquestrador.extrair(
        escopos, extrator, progresso=progresso, ao_conhecer_total=definir_total
    )
    print()
    print()
    print(f"⏱️  duração: {time.monotonic() - inicio:.0f}s")
    return ou_sair(resultado)

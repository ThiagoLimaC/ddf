"""Wizard interativo do ddf — fluxo completo via click + questionary."""

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import click

from ddf.infrastructure.adapters.cli import avisos, prompts
from ddf.infrastructure.adapters.cli.etapas import analise, curadoria, extracao, geracao
from ddf.infrastructure.adapters.cli.registro import descoberta
from ddf.infrastructure.adapters.orchestrator.orquestrador_paralelo import (
    OrquestradorParalelo,
)

_TOTAL_ETAPAS = 11

_BANNER = r"""

                                  __...--~~~~~-._   _.-~~~~~--...__
                                //               `V'               \\
                               //                 |                 \\
                              //__...--~~~~~~-._  |  _.-~~~~~~--...__\\
                             //__.....----~~~~._\ | /_.~~~~----.....__\\
                            ====================\\|//====================
                                                `---`
      
                 ██████╗  █████╗ ████████╗ █████╗     ██████╗ ██╗ ██████╗████████╗
                 ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗    ██╔══██╗██║██╔════╝╚══██╔══╝
                 ██║  ██║███████║   ██║   ███████║    ██║  ██║██║██║        ██║
                 ██║  ██║██╔══██║   ██║   ██╔══██║    ██║  ██║██║██║        ██║
                 ██████╔╝██║  ██║   ██║   ██║  ██║    ██████╔╝██║╚██████╗   ██║
                 ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝    ╚═════╝ ╚═╝ ╚═════╝   ╚═╝
        
        ───────────────────────────────────────────────────────────────────────────────────

        > extração, curadoria e documentação versionável de bancos relacionais | [v1.0.0] <
                        :: Construído por ThiagoLimaC // [ 6/8/2026 ] ::
                                [ github.com/ThiagoLimaC/ddf ]
"""

_BOAS_VINDAS = (
    "\n"
    "\n"
    "Bem-vindo ao ddf. As próximas etapas conectam a uma fonte de dados, extraem e curam a\n"
    "estrutura das tabelas e geram os artefatos de documentação escolhidos."
)


def _configurar_logging() -> None:
    """Torna visível no terminal o log INFO+ de qualquer módulo do ddf.

    O nível padrão do logger raiz do Python é WARNING, e nada mais no
    processo registra um handler — sem isso, todo `logger.info(...)` de
    Adapters (ex.: streaming ativado numa tabela grande) é descartado
    silenciosamente antes de chegar a qualquer lugar visível.
    """
    logger_ddf = logging.getLogger("ddf")
    logger_ddf.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger_ddf.addHandler(handler)


def _sair_se_vazio(itens: Sequence[object], mensagem: str) -> None:
    """Imprime `mensagem` e sai com código 1 se `itens` estiver vazio.

    `OrquestradorParalelo.extrair`/`aplicar_sobrescritas` nunca devolvem
    Falha — falha individual de item vira Aviso, o lote inteiro sempre
    "tem sucesso" mesmo com 0 itens processados (ver docstring de ambos).
    Esta função é o único ponto que decide que um lote vazio não deve
    seguir para as etapas seguintes do wizard.
    """
    if not itens:
        print(mensagem)
        sys.exit(1)


@click.command()
def executar() -> None:
    """Executa o wizard interativo do ddf, da conexão aos artefatos gerados.

    Descoberta de plugins roda uma única vez; as etapas 1-11 repetem a cada
    "Executar novamente?" confirmado, sem precisar reiniciar o processo.
    """
    prompts.imprimir_destacado(_BANNER, prompts.COR_DESTAQUE)
    prompts.imprimir_destacado(_BOAS_VINDAS, prompts.COR_SECUNDARIA, negrito=False)
    avisos.exibir_avisos(
        descoberta.descobrir_extratores() + descoberta.descobrir_geradores()
    )
    while True:
        prompts.cabecalho_etapa(1, _TOTAL_ETAPAS, "Escolher fonte e conectar")
        extrator, configuracao, escopos_disponiveis = extracao.conectar()

        prompts.cabecalho_etapa(2, _TOTAL_ETAPAS, "Escolher escopos")
        escopos = prompts.escolher_multiplos(
            "Escolha um ou mais escopos:", escopos_disponiveis
        )

        prompts.cabecalho_etapa(3, _TOTAL_ETAPAS, "Escolher estratégia de amostragem")
        extracao.configurar_amostragem(configuracao)

        prompts.cabecalho_etapa(4, _TOTAL_ETAPAS, "Extrair tabelas")
        orquestrador = OrquestradorParalelo()
        tabelas = extracao.extrair(orquestrador, extrator, escopos)
        _sair_se_vazio(tabelas, "Nenhuma tabela extraída com sucesso.")

        prompts.cabecalho_etapa(
            5, _TOTAL_ETAPAS, "Gerar skeletons e pausar para curadoria"
        )
        diretorio_overrides = Path(
            prompts.texto(
                "Diretório de overrides:", default="overrides", dica_limpar=True
            )
        ).expanduser()
        sobrescrita = curadoria.curar(orquestrador, diretorio_overrides, tabelas)

        prompts.cabecalho_etapa(6, _TOTAL_ETAPAS, "Aplicar sobrescritas")
        banco_curado = curadoria.aplicar_sobrescritas(
            orquestrador, sobrescrita, tabelas
        )
        _sair_se_vazio(banco_curado.tabelas, "Nenhuma tabela curada com sucesso.")

        prompts.cabecalho_etapa(7, _TOTAL_ETAPAS, "Escolher geradores")
        nomes_geradores = analise.escolher_geradores()
        analisadores_ordenados = analise.validar_selecao(nomes_geradores)

        prompts.cabecalho_etapa(8, _TOTAL_ETAPAS, "Analisar")
        banco_analisado = analise.analisar(analisadores_ordenados, banco_curado)

        prompts.cabecalho_etapa(9, _TOTAL_ETAPAS, "Escolher destino")
        destino = Path(
            prompts.texto(
                "Diretório de destino dos artefatos:",
                default="artefatos",
                dica_limpar=True,
            )
        ).expanduser()

        prompts.cabecalho_etapa(10, _TOTAL_ETAPAS, "Confirmar execução")
        geracao.confirmar_execucao(nomes_geradores, destino)

        prompts.cabecalho_etapa(11, _TOTAL_ETAPAS, "Executar geradores")
        geracao.executar_geradores(nomes_geradores, banco_analisado, destino)

        if not prompts.confirmar("Executar novamente?", default=False):
            break


if __name__ == "__main__":
    executar()

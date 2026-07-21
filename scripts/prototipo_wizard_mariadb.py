"""Rascunho de CLI pra testar Extratores reais (Postgres/MariaDB) manualmente.

Não faz parte do produto (fora de src/) — é um script exploratório, no
mesmo espírito do prototipo_wizard.py usado pra validar o ExtratorPostgres
manualmente antes do wizard real (issue #7 da CLI) existir. Serve de base
pra ir criando testes/roteiros de exploração contra bancos reais (ex.:
relational.fel.cvut.cz), sem esperar o wizard de produção.

Uso:
    uv run python scripts/prototipo_wizard_mariadb.py
"""

import itertools
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import questionary

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ContextoDeAnalise,
    iniciar_contexto,
)
from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_coluna import (
    AnalisadorDeMetricasDeColuna,
)
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_tabela import (
    AnalisadorDeMetricasDeTabela,
)
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)
from ddf.infrastructure.adapters.generators.gerador_contexto_de_ia import (
    GeradorContextoDeIA,
)
from ddf.infrastructure.adapters.generators.gerador_dbt import GeradorDbt
from ddf.infrastructure.adapters.generators.gerador_markdown import GeradorMarkdown
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)

_GERADORES_DISPONIVEIS = ["Markdown", "dbt", "ContextoDeIA"]
_QUADROS_AMPULHETA = ("⏳", "⌛")


@contextmanager
def _ampulheta(mensagem: str) -> Iterator[None]:
    """Anima uma ampulheta virando ao lado da mensagem enquanto o bloco roda.

    Roda numa thread separada porque a chamada de rede dentro do `with` é
    síncrona/bloqueante — sem isso não haveria como atualizar o quadro
    enquanto se espera a resposta do banco.

    Args:
        mensagem: texto exibido ao lado do ícone.
    """
    parar = threading.Event()

    def _animar() -> None:
        for quadro in itertools.cycle(_QUADROS_AMPULHETA):
            if parar.is_set():
                return
            print(f"\r\x1b[K{quadro} {mensagem}", end="", flush=True)
            time.sleep(0.3)

    thread = threading.Thread(target=_animar, daemon=True)
    thread.start()
    try:
        yield
    finally:
        parar.set()
        thread.join()


def _construir_extrator(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta qual fonte usar e monta o Extrator concreto correspondente."""
    fonte = questionary.select("Qual fonte?", choices=["Postgres", "MariaDB"]).ask()
    if fonte is None:
        sys.exit(0)

    if fonte == "Postgres":
        dsn = questionary.text(
            "Connection string do Postgres:",
            default="postgresql://admin:admin@localhost:5432/postgres",
        ).ask()
        return ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    host = questionary.text("Host do MariaDB:", default="localhost").ask()
    port = int(questionary.text("Porta:", default="3306").ask())
    user = questionary.text("Usuário:", default="root").ask()
    password = questionary.password("Senha:").ask()
    return ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )


def _escolher_multiplos(mensagem: str, escolhas: list[str]) -> list[str]:
    """Checkbox com filtro por digitação — permite escolher um ou vários.

    Listas longas ficam difíceis de rolar em terminais pequenos; a forma
    rápida de achar um item é digitar parte do nome pra filtrar em vez de
    navegar pelas setas.
    """
    selecionados = questionary.checkbox(
        mensagem,
        choices=escolhas,
        use_search_filter=True,
        use_jk_keys=False,
        instruction="(digite para filtrar, espaço marca, enter confirma)",
    ).ask()
    if not selecionados:
        sys.exit(0)
    return selecionados


def main() -> None:
    """Conecta, lista escopos (multi-seleção) e extrai todas as suas tabelas."""
    percentual = float(
        questionary.text("Percentual de amostragem (0-100]:", default="10").ask()
    )
    configuracao = ConfiguracaoDeExtracao(
        estrategia=PercentualDeLinhas(percentual=percentual)
    )
    extrator = _construir_extrator(configuracao)

    print("\nListando escopos...")
    resultado_escopos = extrator.listar_escopos()
    if isinstance(resultado_escopos, Falha):
        print(f"Falha: {resultado_escopos.erro}")
        sys.exit(1)
    print(f"{len(resultado_escopos.valor)} escopos encontrados.")

    escopos_escolhidos = _escolher_multiplos(
        "Escolha um ou mais escopos:", resultado_escopos.valor
    )

    tabelas_escolhidas: list[tuple[str, str]] = []
    for escopo in escopos_escolhidos:
        resultado_tabelas = extrator.listar_tabelas(escopo)
        if isinstance(resultado_tabelas, Falha):
            print(f"Falha ao listar tabelas de '{escopo}': {resultado_tabelas.erro}")
            continue
        tabelas_escolhidas.extend((escopo, nome) for _, nome in resultado_tabelas.valor)
    if not tabelas_escolhidas:
        print("Nenhuma tabela disponível nos escopos escolhidos.")
        sys.exit(0)

    diretorio_overrides = Path(
        questionary.text("Diretório de overrides:", default="overrides").ask()
    )
    sobrescrita = SobrescritaDeTabela(diretorio_overrides)

    tabelas_extraidas = _extrair_tabelas(extrator, tabelas_escolhidas)
    if not tabelas_extraidas:
        print("\nNenhuma tabela extraída com sucesso.")
        sys.exit(1)

    print("\nGerando/atualizando skeletons de sobrescrita...")
    for (escopo, tabela), tabela_extraida in tabelas_extraidas.items():
        resultado_skeleton = sobrescrita(tabela_extraida)
        if isinstance(resultado_skeleton, Falha):
            print(
                f"Falha ao gerar skeleton de '{escopo}.{tabela}': "
                f"{resultado_skeleton.erro}"
            )
    print()

    questionary.press_any_key_to_continue(
        message="Edite os YAMLs de overrides acima e aperte uma tecla para continuar..."
    ).ask()

    banco_curado = BancoCurado(
        tabelas=_aplicar_sobrescritas(sobrescrita, tabelas_extraidas)
    )
    if not banco_curado.tabelas:
        print("\nNenhuma tabela curada com sucesso.")
        sys.exit(1)

    _executar_geradores(banco_curado)


def _extrair_tabelas(
    extrator: Extrator, tabelas_escolhidas: list[tuple[str, str]]
) -> dict[tuple[str, str], TabelaExtraida]:
    """Extrai cada tabela escolhida.

    Args:
        extrator: Extrator concreto já construído.
        tabelas_escolhidas: pares (escopo, tabela) selecionados pelo usuário.

    Returns:
        Mapa (escopo, tabela) -> TabelaExtraida das tabelas extraídas com
        sucesso (falhas individuais são reportadas e puladas).
    """
    tabelas_extraidas: dict[tuple[str, str], TabelaExtraida] = {}
    total = len(tabelas_escolhidas)
    for indice, (escopo, tabela) in enumerate(tabelas_escolhidas, start=1):
        with _ampulheta(f"Extraindo tabelas... ({indice}/{total}) {escopo}.{tabela}"):
            resultado_tabela = extrator.extrair_tabela(escopo, tabela)
        if isinstance(resultado_tabela, Falha):
            print(f"\nFalha ao extrair '{escopo}.{tabela}': {resultado_tabela.erro}")
            continue

        tabela_extraida = resultado_tabela.valor
        if resultado_tabela.avisos:
            print(f"\nAvisos da extração de '{escopo}.{tabela}':")
            for aviso in resultado_tabela.avisos:
                print(f"  [{aviso.origem}] {aviso.mensagem}")
        tabelas_extraidas[(escopo, tabela)] = tabela_extraida

    print()
    return tabelas_extraidas


def _aplicar_sobrescritas(
    sobrescrita: SobrescritaDeTabela,
    tabelas_extraidas: dict[tuple[str, str], TabelaExtraida],
) -> list[TabelaCurada]:
    """Reaplica a sobrescrita após a pausa, agora lendo a curadoria já editada.

    Args:
        sobrescrita: instância de SobrescritaDeTabela já configurada.
        tabelas_extraidas: tabelas extraídas cujos skeletons já foram
            gerados/atualizados numa primeira passada.

    Returns:
        Lista de TabelaCurada das tabelas cuja sobrescrita foi aplicada com
        sucesso (falhas individuais são reportadas e puladas).
    """
    tabelas_curadas: list[TabelaCurada] = []
    for (escopo, tabela), tabela_extraida in tabelas_extraidas.items():
        resultado_curadoria = sobrescrita(tabela_extraida)
        if isinstance(resultado_curadoria, Falha):
            print(
                f"Falha ao aplicar sobrescrita de '{escopo}.{tabela}': "
                f"{resultado_curadoria.erro}"
            )
            continue
        for aviso in resultado_curadoria.avisos:
            print(f"  [{aviso.origem}] {aviso.mensagem}")
        tabelas_curadas.append(resultado_curadoria.valor)

    return tabelas_curadas


def _executar_geradores(banco_curado: BancoCurado) -> None:
    """Pergunta quais geradores rodar; os três rodam de verdade.

    Args:
        banco_curado: banco curado a analisar/documentar.
    """
    geradores_escolhidos = _escolher_multiplos(
        "Escolha um ou mais geradores:", _GERADORES_DISPONIVEIS
    )
    print()

    contexto = iniciar_contexto(banco_curado)
    resultado_contexto = _rodar_analisadores(contexto)
    if isinstance(resultado_contexto, Falha):
        print(f"Falha ao calcular métricas: {resultado_contexto.erro}")
        return
    contexto = resultado_contexto.valor
    for aviso in resultado_contexto.avisos:
        print(f"  [{aviso.origem}] {aviso.mensagem}")

    if "Markdown" in geradores_escolhidos:
        _executar_gerador_markdown(contexto.analisado)
    if "dbt" in geradores_escolhidos:
        _executar_gerador_dbt(contexto.analisado)
    if "ContextoDeIA" in geradores_escolhidos:
        _executar_gerador_contexto_de_ia(contexto.analisado)


def _executar_gerador_markdown(banco_analisado: BancoAnalisado) -> None:
    """Roda o GeradorMarkdown sobre o banco já analisado.

    Args:
        banco_analisado: banco curado com as métricas já calculadas.
    """
    destino = Path(
        questionary.text(
            "Diretório de destino do Markdown:", default="docs_gerados"
        ).ask()
    )
    resultado_geracao = GeradorMarkdown()(banco_analisado, destino)
    if isinstance(resultado_geracao, Falha):
        print(f"Falha ao gerar Markdown: {resultado_geracao.erro}")
        return
    for aviso in resultado_geracao.avisos:
        print(f"  [{aviso.origem}] {aviso.mensagem}")
    print(f"GeradorMarkdown: documentação escrita em '{destino}'.")


def _executar_gerador_dbt(banco_analisado: BancoAnalisado) -> None:
    """Roda o GeradorDbt sobre o banco já analisado.

    Args:
        banco_analisado: banco curado com as métricas já calculadas.
    """
    destino = Path(
        questionary.text(
            "Diretório de destino do projeto dbt:", default="dbt_gerado"
        ).ask()
    )
    resultado_geracao = GeradorDbt()(banco_analisado, destino)
    if isinstance(resultado_geracao, Falha):
        print(f"Falha ao gerar projeto dbt: {resultado_geracao.erro}")
        return
    for aviso in resultado_geracao.avisos:
        print(f"  [{aviso.origem}] {aviso.mensagem}")
    print(f"GeradorDbt: projeto dbt escrito em '{destino}'.")


def _executar_gerador_contexto_de_ia(banco_analisado: BancoAnalisado) -> None:
    """Roda o GeradorContextoDeIA sobre o banco já analisado.

    Args:
        banco_analisado: banco curado com as métricas já calculadas.
    """
    destino = Path(
        questionary.text(
            "Diretório de destino do contexto de IA:", default="contexto_ia_gerado"
        ).ask()
    )
    resultado_geracao = GeradorContextoDeIA()(banco_analisado, destino)
    if isinstance(resultado_geracao, Falha):
        print(f"Falha ao gerar contexto de IA: {resultado_geracao.erro}")
        return
    for aviso in resultado_geracao.avisos:
        print(f"  [{aviso.origem}] {aviso.mensagem}")
    print(f"GeradorContextoDeIA: contexto escrito em '{destino}'.")


def _rodar_analisadores(contexto: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]:
    """Roda os dois Analisadores mergeados, na ordem exigida por produz/requer.

    Args:
        contexto: contexto recém-criado a partir do BancoCurado.

    Returns:
        Sucesso com o ContextoDeAnalise enriquecido por ambos os
        Analisadores, ou a primeira Falha encontrada.
    """
    resultado_coluna = AnalisadorDeMetricasDeColuna()(contexto)
    if isinstance(resultado_coluna, Falha):
        return resultado_coluna

    resultado_tabela = AnalisadorDeMetricasDeTabela()(resultado_coluna.valor)
    if isinstance(resultado_tabela, Falha):
        return resultado_tabela

    return Sucesso(
        resultado_tabela.valor,
        avisos=resultado_coluna.avisos + resultado_tabela.avisos,
    )


if __name__ == "__main__":
    main()

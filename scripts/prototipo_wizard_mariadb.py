"""Rascunho de CLI pra testar Extratores reais (Postgres/MariaDB) manualmente.

Não faz parte do produto (fora de src/) — é um script exploratório, no
mesmo espírito do prototipo_wizard.py usado pra validar o ExtratorPostgres
manualmente antes do wizard real (issue #7 da CLI) existir. Serve de base
pra ir criando testes/roteiros de exploração contra bancos reais (ex.:
relational.fel.cvut.cz), sem esperar o wizard de produção.

Uso:
    uv run python scripts/prototipo_wizard_mariadb.py
"""

import sys
from pathlib import Path

import questionary

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)


def _construir_extrator(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta qual fonte usar e monta o Extrator concreto correspondente."""
    fonte = questionary.select(
        "Qual fonte?", choices=["Postgres", "MariaDB"]
    ).ask()
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
    """Checkbox com filtro por digitação — permite escolher um ou vários."""
    selecionados = questionary.checkbox(
        mensagem, choices=escolhas, use_search_filter=True, use_jk_keys=False
    ).ask()
    if not selecionados:
        sys.exit(0)
    return selecionados


def _imprimir_tabela_extraida(tabela: TabelaExtraida) -> None:
    """Imprime um resumo legível de uma TabelaExtraida no terminal."""
    print(f"\n== {tabela.nome_escopo}.{tabela.nome_tabela} ==")
    print(f"Total de linhas (estimado): {tabela.total_linhas}")
    print(f"Tamanho da amostra: {tabela.metadados_amostra.tamanho_amostra}")
    print(f"{'Coluna':<25}{'Tipo':<12}{'PK':<5}{'FK':<5}Referência")
    for coluna in tabela.colunas:
        referencia = (
            f"{coluna.referencia.nome_escopo}.{coluna.referencia.nome_tabela}"
            f".{coluna.referencia.nome_coluna}"
            if coluna.referencia
            else ""
        )
        print(
            f"{coluna.nome:<25}{coluna.tipo_dado.categoria.value:<12}"
            f"{'x' if coluna.chave_primaria else '':<5}"
            f"{'x' if coluna.chave_estrangeira else '':<5}{referencia}"
        )


def main() -> None:
    """Conecta, lista escopos/tabelas (multi-seleção) e aplica sobrescrita."""
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
        "Escolha um ou mais escopos (espaço marca, enter confirma):",
        resultado_escopos.valor,
    )

    tabelas_por_escopo: dict[str, list[str]] = {}
    for escopo in escopos_escolhidos:
        resultado_tabelas = extrator.listar_tabelas(escopo)
        if isinstance(resultado_tabelas, Falha):
            print(f"Falha ao listar tabelas de '{escopo}': {resultado_tabelas.erro}")
            continue
        tabelas_por_escopo[escopo] = [nome for _, nome in resultado_tabelas.valor]

    escolhas_tabela = [
        questionary.Choice(title=f"{escopo}.{tabela}", value=(escopo, tabela))
        for escopo, tabelas in tabelas_por_escopo.items()
        for tabela in tabelas
    ]
    if not escolhas_tabela:
        print("Nenhuma tabela disponível nos escopos escolhidos.")
        sys.exit(0)

    tabelas_escolhidas = questionary.checkbox(
        "Escolha uma ou mais tabelas pra extrair:",
        choices=escolhas_tabela,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    if not tabelas_escolhidas:
        sys.exit(0)

    diretorio_overrides = Path(
        questionary.text("Diretório de overrides:", default="overrides").ask()
    )
    sobrescrita = SobrescritaDeTabela(diretorio_overrides)

    for escopo, tabela in tabelas_escolhidas:
        resultado_tabela = extrator.extrair_tabela(escopo, tabela)
        if isinstance(resultado_tabela, Falha):
            print(f"\nFalha ao extrair '{escopo}.{tabela}': {resultado_tabela.erro}")
            continue

        tabela_extraida = resultado_tabela.valor
        _imprimir_tabela_extraida(tabela_extraida)
        if resultado_tabela.avisos:
            print("Avisos da extração:")
            for aviso in resultado_tabela.avisos:
                print(f"  [{aviso.origem}] {aviso.mensagem}")

        resultado_curadoria = sobrescrita(tabela_extraida)
        if isinstance(resultado_curadoria, Falha):
            print(f"Falha ao aplicar sobrescrita: {resultado_curadoria.erro}")
            continue
        caminho_yaml = diretorio_overrides / escopo / f"{tabela}.yaml"
        print(f"Sobrescrita aplicada — skeleton em {caminho_yaml}")
        for aviso in resultado_curadoria.avisos:
            print(f"  [{aviso.origem}] {aviso.mensagem}")


if __name__ == "__main__":
    main()

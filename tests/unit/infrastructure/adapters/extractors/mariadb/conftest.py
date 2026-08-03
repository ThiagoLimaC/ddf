"""Fixtures compartilhadas dos testes de ExtratorMariaDB."""

from unittest.mock import MagicMock

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.infrastructure.adapters.extractors.estrategias.amostragem_por_faixa import (
    AmostragemPorFaixa,
)
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao com PercentualDeLinhas(10%)."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=10.0))


@pytest.fixture
def configuracao_por_faixa() -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao com AmostragemPorFaixa(10%)."""
    return ConfiguracaoDeExtracao(estrategia=AmostragemPorFaixa(percentual=10.0))


@pytest.fixture
def configuracao_integral(
    estrategia_integral: EstrategiaDeAmostragem,
) -> ConfiguracaoDeExtracao:
    """Retorna uma ConfiguracaoDeExtracao que pede AmostragemIntegral."""
    return ConfiguracaoDeExtracao(estrategia=estrategia_integral)


@pytest.fixture
def pool_classe_fake(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Substitui PooledDB por um mock, retorna a classe mockada."""
    classe_fake = MagicMock()
    monkeypatch.setattr(
        "ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb.PooledDB",
        classe_fake,
    )
    return classe_fake


def montar_metadados_side_effect(
    tabela: str,
    colunas: list[tuple[str, str, str, int | None, int | None, int | None, str]],
    pks: list[str] | None = None,
    fks: list[tuple[str, str, str, str, str]] | None = None,
    unicas: list[tuple[str, str]] | None = None,
    check_clauses: list[str] | None = None,
    total_linhas: int | None = 0,
) -> list[list[tuple[object, ...]]]:
    """Monta os 6 `fetchall` de `_obter_metadados_schema` pra uma única tabela.

    Cada linha crua recebe `tabela` como 1º campo, espelhando o formato
    schema-wide que as 6 queries de `_obter_metadados_schema` retornam de
    verdade — cenários com mais de uma tabela no mesmo escopo (ex.: colisão
    de `constraint_name` entre tabelas) constroem o `side_effect`
    manualmente, sem este helper.

    Returns:
        As 6 listas, na ordem que `_obter_metadados_schema` executa as
        queries (colunas, PK, FK, UNIQUE, JSON, total_linhas) — quem chama
        ainda precisa acrescentar a linha da amostra por conta própria.
    """
    return [
        [(tabela, *coluna) for coluna in colunas],
        [(tabela, pk) for pk in (pks or [])],
        [(tabela, *fk) for fk in (fks or [])],
        [(tabela, *unica) for unica in (unicas or [])],
        [(tabela, clause) for clause in (check_clauses or [])],
        [(tabela, total_linhas)],
    ]

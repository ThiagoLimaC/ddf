"""Testes de AnalisadorDeMetricasDeTabela."""

from collections.abc import Callable

import polars as pl
import pytest

from ddf.domain.model.analysis import (
    ContextoDeAnalise,
    MetricasBaseColuna,
    MetricasBaseTabela,
)
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.curation import ColunaCurada, TabelaCurada
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_coluna import (
    AnalisadorDeMetricasDeColuna,
)
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_tabela import (
    AnalisadorDeMetricasDeTabela,
)
from ddf.pipeline.compor import compor


def _metrica(*, percentual_nulo: float) -> MetricasBaseColuna:
    return MetricasBaseColuna(
        percentual_nulo=percentual_nulo,
        percentual_unico=0.0,
        valores_frequentes=[],
        minimo=None,
        maximo=None,
        formato_detectado=None,
    )


def _tabela_curada(nome_tabela: str, colunas: list[ColunaCurada]) -> TabelaCurada:
    return TabelaCurada(
        nome_tabela=nome_tabela,
        nome_escopo="public",
        colunas=colunas,
        total_linhas=0,
        amostra=None,
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=0
        ),
    )


# Caminho feliz


def test_analisador_de_metricas_de_tabela_satisfaz_analisador() -> None:
    """Caminho feliz: AnalisadorDeMetricasDeTabela conforma ao Port Analisador."""
    assert isinstance(AnalisadorDeMetricasDeTabela(), Analisador)


def test_calcula_completude_como_media_de_100_menos_percentual_nulo(
    tipo_integer: TipoDeDado,
    tipo_varchar: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Caminho feliz: completude é a média de (100 - percentual_nulo) das colunas."""
    tabela = _tabela_curada(
        "clientes",
        colunas=[
            ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True),
            ColunaCurada(nome="email", tipo_dado=tipo_varchar),
        ],
    )
    contexto = construir_contexto([tabela])
    tabela_analisada = contexto.analisado.tabelas[0]
    tabela_analisada.colunas[0].metricas.append(_metrica(percentual_nulo=0.0))
    tabela_analisada.colunas[1].metricas.append(_metrica(percentual_nulo=20.0))

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    metricas_tabela = resultado.valor.analisado.tabelas[0].metricas
    assert len(metricas_tabela) == 1
    assert metricas_tabela[0].completude == 90.0


def test_processa_multiplas_tabelas_com_completude_propria(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Caminho feliz: cada tabela recebe sua própria MetricasBaseTabela."""
    tabela_a = _tabela_curada(
        "a", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    tabela_b = _tabela_curada(
        "b", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela_a, tabela_b])
    contexto.analisado.tabelas[0].colunas[0].metricas.append(
        _metrica(percentual_nulo=0.0)
    )
    contexto.analisado.tabelas[1].colunas[0].metricas.append(
        _metrica(percentual_nulo=100.0)
    )

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    tabelas = resultado.valor.analisado.tabelas
    assert tabelas[0].metricas[0].completude == 100.0
    assert tabelas[1].metricas[0].completude == 0.0


# Erro esperado


def test_falha_se_metricas_base_coluna_ausente(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Erro esperado: coluna sem MetricasBaseColuna calculada gera Falha."""
    tabela = _tabela_curada(
        "clientes", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela])

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Falha)
    assert "ausente" in resultado.erro
    assert "public.clientes.id" in resultado.erro


def test_falha_se_metricas_base_coluna_duplicada(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Erro esperado: coluna com MetricasBaseColuna duplicada gera Falha."""
    tabela = _tabela_curada(
        "clientes", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela])
    coluna_analisada = contexto.analisado.tabelas[0].colunas[0]
    coluna_analisada.metricas.append(_metrica(percentual_nulo=0.0))
    coluna_analisada.metricas.append(_metrica(percentual_nulo=10.0))

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Falha)
    assert "duplicada" in resultado.erro
    assert "public.clientes.id" in resultado.erro


def test_interrompe_no_primeiro_erro_sem_processar_demais_tabelas(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Erro esperado: Falha na primeira tabela interrompe antes da segunda."""
    tabela_sem_metrica = _tabela_curada(
        "a", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    tabela_ok = _tabela_curada(
        "b", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela_sem_metrica, tabela_ok])
    contexto.analisado.tabelas[1].colunas[0].metricas.append(
        _metrica(percentual_nulo=0.0)
    )

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Falha)
    assert contexto.analisado.tabelas[1].metricas == []


# Borda


def test_tabela_sem_colunas_tem_completude_zero(
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Borda: tabela sem colunas recebe completude=0.0 sem dividir por zero."""
    tabela = _tabela_curada("vazia", colunas=[])
    contexto = construir_contexto([tabela])

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.analisado.tabelas[0].metricas[0].completude == 0.0


def test_completude_com_divisao_nao_exata_preserva_precisao_de_ponto_flutuante(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Borda: 200/3 gera dízima periódica — sem round()/truncamento no cálculo."""
    tabela = _tabela_curada(
        "clientes",
        colunas=[
            ColunaCurada(nome="a", tipo_dado=tipo_integer),
            ColunaCurada(nome="b", tipo_dado=tipo_integer),
            ColunaCurada(nome="c", tipo_dado=tipo_integer),
        ],
    )
    contexto = construir_contexto([tabela])
    colunas = contexto.analisado.tabelas[0].colunas
    for coluna, percentual_nulo in zip(colunas, [0.0, 0.0, 100.0], strict=True):
        coluna.metricas.append(_metrica(percentual_nulo=percentual_nulo))

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    completude = resultado.valor.analisado.tabelas[0].metricas[0].completude
    assert completude == pytest.approx(200 / 3)
    assert 0 <= completude <= 100


def test_todas_colunas_sem_nulo_tem_completude_cem(
    tipo_integer: TipoDeDado,
    tipo_varchar: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Borda: nenhuma coluna nula resulta em completude=100.0."""
    tabela = _tabela_curada(
        "clientes",
        colunas=[
            ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True),
            ColunaCurada(nome="email", tipo_dado=tipo_varchar),
        ],
    )
    contexto = construir_contexto([tabela])
    for coluna in contexto.analisado.tabelas[0].colunas:
        coluna.metricas.append(_metrica(percentual_nulo=0.0))

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.analisado.tabelas[0].metricas[0].completude == 100.0


def test_todas_colunas_totalmente_nulas_tem_completude_zero(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Borda: todas as colunas 100% nulas resulta em completude=0.0."""
    tabela = _tabela_curada(
        "clientes", colunas=[ColunaCurada(nome="obs", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela])
    contexto.analisado.tabelas[0].colunas[0].metricas.append(
        _metrica(percentual_nulo=100.0)
    )

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.analisado.tabelas[0].metricas[0].completude == 0.0


def test_nao_muta_o_contexto_original(
    tipo_integer: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Borda: chamar o Analisador não altera o ContextoDeAnalise recebido.

    Reabertura de escopo da issue #53: o Analisador passou a devolver um
    ContextoDeAnalise novo em vez de mutar `entrada` in-place, deixando a
    porta aberta para uma futura paralelização de Analisadores sobre o
    mesmo contexto (mutação compartilhada seria uma race condition).
    """
    tabela = _tabela_curada(
        "clientes", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
    )
    contexto = construir_contexto([tabela])
    contexto.analisado.tabelas[0].colunas[0].metricas.append(
        _metrica(percentual_nulo=0.0)
    )

    resultado = AnalisadorDeMetricasDeTabela()(contexto)

    assert isinstance(resultado, Sucesso)
    assert resultado.valor is not contexto
    assert contexto.analisado.tabelas[0].metricas == []
    assert resultado.valor.analisado.tabelas[0].metricas[0].completude == 100.0


# Open/Closed — composição real com AnalisadorDeMetricasDeColuna


def test_compoe_com_analisador_de_metricas_de_coluna_sem_editar_nenhum_dos_dois(
    tipo_integer: TipoDeDado,
    tipo_varchar: TipoDeDado,
    construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
) -> None:
    """Open/Closed: compor() encadeia os dois Analisadores sem exigir edição em nenhum.

    AnalisadorDeMetricasDeColuna (issue #11) não foi alterado por esta issue.
    A comunicação entre os dois se dá só pelo Port Analisador e por
    ColunaAnalisada.metricas — prova de que adicionar este Analisador foi uma
    extensão, não uma modificação.
    """
    amostra = pl.DataFrame(
        {"id": [1, 2, 3, 4], "email": ["a@x.com", None, "b@x.com", None]}
    )
    tabela = TabelaCurada(
        nome_tabela="clientes",
        nome_escopo="public",
        colunas=[
            ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True),
            ColunaCurada(nome="email", tipo_dado=tipo_varchar),
        ],
        total_linhas=4,
        amostra=amostra,
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=4
        ),
    )
    contexto = construir_contexto([tabela])
    pipeline = compor(AnalisadorDeMetricasDeColuna(), AnalisadorDeMetricasDeTabela())

    resultado = pipeline(contexto)

    assert isinstance(resultado, Sucesso)
    tabela_analisada = resultado.valor.analisado.tabelas[0]
    metrica_coluna = tabela_analisada.colunas[1].metricas[0]
    assert isinstance(metrica_coluna, MetricasBaseColuna)
    assert metrica_coluna.percentual_nulo == 50.0
    metrica_tabela = tabela_analisada.metricas[0]
    assert isinstance(metrica_tabela, MetricasBaseTabela)
    # id: 0% nulo, email: 50% nulo -> completude = (100 + 50) / 2
    assert metrica_tabela.completude == 75.0

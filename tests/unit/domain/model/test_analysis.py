"""Testes do Analysis Context: métricas, ColunaAnalisada, TabelaAnalisada, etc."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
    iniciar_contexto,
)
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.curation import BancoCurado, ColunaCurada, TabelaCurada


# Caminho feliz
def test_cria_metricas_base_coluna_com_origem_padrao() -> None:
    """Caminho feliz: MetricasBaseColuna assume origem do Analisador que produz."""
    metricas = MetricasBaseColuna(
        percentual_nulo=10.0,
        percentual_unico=90.0,
        valores_frequentes=["a", "b"],
        minimo="a",
        maximo="z",
        formato_detectado=None,
    )

    assert metricas.origem == "AnalisadorDeMetricasDeColuna"


def test_cria_metricas_base_tabela_com_origem_padrao() -> None:
    """Caminho feliz: MetricasBaseTabela assume origem do Analisador que produz."""
    metricas = MetricasBaseTabela(completude=95.5)

    assert metricas.origem == "AnalisadorDeMetricasDeTabela"


def test_cria_coluna_analisada_com_metricas(tipo_integer: TipoDeDado) -> None:
    """Caminho feliz: ColunaAnalisada acumula Value Objects de Analisadores."""
    metricas = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=100.0,
        valores_frequentes=[],
        minimo="1",
        maximo="10",
        formato_detectado=None,
    )
    coluna = ColunaAnalisada(
        nome="id", tipo_dado=tipo_integer, chave_primaria=True, metricas=[metricas]
    )

    assert coluna.metricas == [metricas]


def test_cria_tabela_analisada_com_metricas(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Caminho feliz: TabelaAnalisada agrega colunas analisadas e métricas de tabela."""
    tabela = TabelaAnalisada(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=[ColunaAnalisada(nome="id", tipo_dado=tipo_integer)],
        total_linhas=10,
        metadados_amostra=metadados_de_amostra,
        metricas=[MetricasBaseTabela(completude=100.0)],
    )

    assert tabela.metricas[0].completude == 100.0


def test_cria_banco_analisado_com_multiplas_tabelas(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Caminho feliz: BancoAnalisado agrega múltiplas TabelaAnalisada distintas."""
    colunas = [ColunaAnalisada(nome="id", tipo_dado=tipo_integer)]
    pedidos = TabelaAnalisada(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=colunas,
        total_linhas=10,
        metadados_amostra=metadados_de_amostra,
    )
    clientes = TabelaAnalisada(
        nome_tabela="clientes",
        nome_escopo="public",
        colunas=colunas,
        total_linhas=5,
        metadados_amostra=metadados_de_amostra,
    )

    banco = BancoAnalisado(tabelas=[pedidos, clientes])

    assert len(banco.tabelas) == 2


def test_iniciar_contexto_cria_banco_analisado_vazio_a_partir_do_curado(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Caminho feliz: iniciar_contexto copia estrutura curada com metricas vazias."""
    tabela_curada = TabelaCurada(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=[
            ColunaCurada(
                nome="id", tipo_dado=tipo_integer, papel_de_negocio="Identificador"
            )
        ],
        total_linhas=10,
        papel_de_negocio="Tabela fato de pedidos",
        amostra=None,
        metadados_amostra=metadados_de_amostra,
    )
    curado = BancoCurado(tabelas=[tabela_curada])

    contexto = iniciar_contexto(curado)

    assert contexto.curado is curado
    tabela_analisada = contexto.analisado.tabelas[0]
    assert tabela_analisada.nome_tabela == "pedidos"
    assert tabela_analisada.papel_de_negocio == "Tabela fato de pedidos"
    assert tabela_analisada.metricas == []
    coluna_analisada = tabela_analisada.colunas[0]
    assert coluna_analisada.papel_de_negocio == "Identificador"
    assert coluna_analisada.metricas == []


def test_iniciar_contexto_com_banco_curado_sem_tabelas() -> None:
    """Caminho feliz: BancoCurado sem tabelas gera BancoAnalisado sem tabelas."""
    curado = BancoCurado(tabelas=[])

    contexto = iniciar_contexto(curado)

    assert contexto.analisado.tabelas == []


# Erro esperado
def test_metricas_base_coluna_percentual_nulo_fora_do_intervalo() -> None:
    """Erro esperado: percentual_nulo fora de 0-100."""
    with pytest.raises(ValidationError, match="percentual_nulo"):
        MetricasBaseColuna(
            percentual_nulo=101.0,
            percentual_unico=50.0,
            valores_frequentes=[],
            minimo=None,
            maximo=None,
            formato_detectado=None,
        )


def test_metricas_base_coluna_percentual_unico_fora_do_intervalo() -> None:
    """Erro esperado: percentual_unico fora de 0-100."""
    with pytest.raises(ValidationError, match="percentual_unico"):
        MetricasBaseColuna(
            percentual_nulo=10.0,
            percentual_unico=-1.0,
            valores_frequentes=[],
            minimo=None,
            maximo=None,
            formato_detectado=None,
        )


def test_metricas_base_coluna_valores_frequentes_acima_do_limite() -> None:
    """Erro esperado: valores_frequentes com mais de 10 itens."""
    with pytest.raises(ValidationError, match="valores_frequentes"):
        MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=100.0,
            valores_frequentes=[str(i) for i in range(11)],
            minimo=None,
            maximo=None,
            formato_detectado=None,
        )


def test_metricas_base_tabela_completude_fora_do_intervalo() -> None:
    """Erro esperado: completude fora de 0-100."""
    with pytest.raises(ValidationError, match="completude"):
        MetricasBaseTabela(completude=150.0)


def test_metricas_base_coluna_e_imutavel() -> None:
    """Erro esperado: MetricaDeColuna é Value Object frozen, não aceita mutação."""
    metricas = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=0.0,
        valores_frequentes=[],
        minimo=None,
        maximo=None,
        formato_detectado=None,
    )

    with pytest.raises(ValidationError, match="frozen"):
        metricas.percentual_nulo = 50.0  # type: ignore[misc]


def test_metricas_base_tabela_e_imutavel() -> None:
    """Erro esperado: MetricaDeTabela é Value Object frozen, não aceita mutação."""
    metricas = MetricasBaseTabela(completude=100.0)

    with pytest.raises(ValidationError, match="frozen"):
        metricas.completude = 50.0  # type: ignore[misc]


def test_coluna_analisada_fk_sem_referencia_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: chave_estrangeira=True sem tabela/coluna referenciada."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaAnalisada(
            nome="cliente_id", tipo_dado=tipo_integer, chave_estrangeira=True
        )


def test_coluna_analisada_referencia_sem_fk_levanta_validation_error(
    tipo_integer: TipoDeDado,
) -> None:
    """Erro esperado: referência preenchida sem chave_estrangeira=True."""
    with pytest.raises(ValidationError, match="chave_estrangeira"):
        ColunaAnalisada(
            nome="cliente_id",
            tipo_dado=tipo_integer,
            tabela_referenciada="clientes",
            coluna_referenciada="id",
        )


def test_tabela_analisada_total_linhas_negativo_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: total_linhas negativo é logicamente impossível."""
    with pytest.raises(ValidationError, match="total_linhas"):
        TabelaAnalisada(
            nome_tabela="pedidos",
            nome_escopo="public",
            colunas=[ColunaAnalisada(nome="id", tipo_dado=tipo_integer)],
            total_linhas=-1,
            metadados_amostra=metadados_de_amostra,
        )


def test_tabela_analisada_com_colunas_duplicadas_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: dois nomes de coluna iguais na mesma tabela."""
    with pytest.raises(ValidationError, match="duplicados"):
        TabelaAnalisada(
            nome_tabela="pedidos",
            nome_escopo="public",
            colunas=[
                ColunaAnalisada(nome="id", tipo_dado=tipo_integer),
                ColunaAnalisada(nome="id", tipo_dado=tipo_integer),
            ],
            total_linhas=10,
            metadados_amostra=metadados_de_amostra,
        )


def test_banco_analisado_com_tabelas_duplicadas_levanta_validation_error(
    tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
) -> None:
    """Erro esperado: mesma (nome_escopo, nome_tabela) duplicada no agregado."""
    tabela = TabelaAnalisada(
        nome_tabela="pedidos",
        nome_escopo="public",
        colunas=[ColunaAnalisada(nome="id", tipo_dado=tipo_integer)],
        total_linhas=10,
        metadados_amostra=metadados_de_amostra,
    )

    with pytest.raises(ValidationError, match="duplicadas"):
        BancoAnalisado(tabelas=[tabela, tabela])

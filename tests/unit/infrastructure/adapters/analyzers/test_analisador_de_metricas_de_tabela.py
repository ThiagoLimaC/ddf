"""Testes de AnalisadorDeMetricasDeTabela."""

from collections.abc import Callable

import polars as pl
import pytest

from ddf.domain.model.analysis import (
    ContextoDeAnalise,
    MetricaDeTabela,
    MetricasBaseColuna,
    MetricasBaseTabela,
    MetricasDeConfianca,
    NivelDeConfianca,
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
from ddf.pipeline.comum.compor import compor


def _metrica(*, percentual_nulo: float) -> MetricasBaseColuna:
    return MetricasBaseColuna(
        percentual_nulo=percentual_nulo,
        percentual_unico=0.0,
        valores_frequentes=[],
        minimo=None,
        maximo=None,
        formato_detectado=None,
    )


def _completude_de(metricas: list[MetricaDeTabela]) -> float:
    metrica = metricas[0]
    assert isinstance(metrica, MetricasBaseTabela)
    return metrica.completude


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


def _tabela_curada_com_amostra(
    nome_tabela: str,
    colunas: list[ColunaCurada],
    *,
    tamanho_amostra: int,
    total_linhas: int,
) -> TabelaCurada:
    return TabelaCurada(
        nome_tabela=nome_tabela,
        nome_escopo="public",
        colunas=colunas,
        total_linhas=total_linhas,
        amostra=None,
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=tamanho_amostra
        ),
    )


class TestFeliz:
    """Caminho feliz."""

    def test_analisador_de_metricas_de_tabela_satisfaz_analisador(
        self,
    ) -> None:
        """AnalisadorDeMetricasDeTabela conforma ao Port Analisador."""
        assert isinstance(AnalisadorDeMetricasDeTabela(), Analisador)

    def test_calcula_completude_como_media_de_100_menos_percentual_nulo(
        self,
        tipo_integer: TipoDeDado,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Completude é a média de (100 - percentual_nulo) das colunas."""
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
        assert len(metricas_tabela) == 2
        assert _completude_de(metricas_tabela) == 90.0

    def test_processa_multiplas_tabelas_com_completude_propria(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Cada tabela recebe sua própria MetricasBaseTabela."""
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
        assert _completude_de(tabelas[0].metricas) == 100.0
        assert _completude_de(tabelas[1].metricas) == 0.0

    def test_amostra_grande_relativa_a_tabela_pequena_tem_confianca_alta(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """n=1.000, N=1.000.000 tem margem de erro ~3,1pp -> ALTA."""
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            tamanho_amostra=1_000,
            total_linhas=1_000_000,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.ALTA


class TestErro:
    """Erro esperado."""

    def test_falha_se_metricas_base_coluna_ausente(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna sem MetricasBaseColuna calculada gera Falha."""
        tabela = _tabela_curada(
            "clientes", colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)]
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Falha)
        assert "ausente" in resultado.erro
        assert "public.clientes.id" in resultado.erro

    def test_falha_se_metricas_base_coluna_duplicada(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna com MetricasBaseColuna duplicada gera Falha."""
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
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Falha na primeira tabela interrompe antes da segunda."""
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


class TestBorda:
    """Bordas."""

    def test_tabela_sem_colunas_tem_completude_zero(
        self,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Tabela sem colunas recebe completude=0.0 sem dividir por zero."""
        tabela = _tabela_curada("vazia", colunas=[])
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        assert _completude_de(resultado.valor.analisado.tabelas[0].metricas) == 0.0

    def test_completude_com_divisao_nao_exata_preserva_precisao_de_ponto_flutuante(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """200/3 gera dízima periódica — sem round()/truncamento no cálculo."""
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
        completude = _completude_de(resultado.valor.analisado.tabelas[0].metricas)
        assert completude == pytest.approx(200 / 3)
        assert 0 <= completude <= 100

    def test_todas_colunas_sem_nulo_tem_completude_cem(
        self,
        tipo_integer: TipoDeDado,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Nenhuma coluna nula resulta em completude=100.0."""
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
        assert _completude_de(resultado.valor.analisado.tabelas[0].metricas) == 100.0

    def test_todas_colunas_totalmente_nulas_tem_completude_zero(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Todas as colunas 100% nulas resulta em completude=0.0."""
        tabela = _tabela_curada(
            "clientes", colunas=[ColunaCurada(nome="obs", tipo_dado=tipo_integer)]
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=100.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        assert _completude_de(resultado.valor.analisado.tabelas[0].metricas) == 0.0

    def test_nao_muta_o_contexto_original(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Chamar o Analisador não altera o ContextoDeAnalise recebido.

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
        assert _completude_de(resultado.valor.analisado.tabelas[0].metricas) == 100.0

    def test_compoe_com_analisador_de_metricas_de_coluna_sem_editar_nenhum_dos_dois(
        self,
        tipo_integer: TipoDeDado,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Open/Closed: compor() encadeia os dois Analisadores sem editar nenhum.

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
        pipeline = compor(
            AnalisadorDeMetricasDeColuna(), AnalisadorDeMetricasDeTabela()
        )

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

    def test_tabela_sem_linhas_tem_confianca_baixa(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """total_linhas=0 é BAIXA direto, sem dividir por zero."""
        tabela = _tabela_curada_com_amostra(
            "vazia",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            tamanho_amostra=0,
            total_linhas=0,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.BAIXA

    def test_amostra_vazia_com_tabela_nao_vazia_tem_confianca_baixa(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """tamanho_amostra=0 com total_linhas>0 é BAIXA, não ZeroDivisionError."""
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            tamanho_amostra=0,
            total_linhas=1000,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.BAIXA

    def test_amostra_igual_a_populacao_tem_confianca_alta_mesmo_pequena(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """n=N (TabelaInteira/AmostragemIntegral) é sempre ALTA, mesmo com N=4."""
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            tamanho_amostra=4,
            total_linhas=4,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.ALTA

    def test_amostra_pequena_relativa_a_tabela_grande_tem_confianca_media(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """n=100, N=1.000.000 tem margem de erro ~9,8pp -> MEDIA, não ALTA.

        O piso binário anterior (`tamanho_amostra >= 100`) tratava esse caso
        como "seguro" — a fórmula de margem de erro discorda, por levar
        `total_linhas` em conta.
        """
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            tamanho_amostra=100,
            total_linhas=1_000_000,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.MEDIA

    def test_amostra_minuscula_relativa_a_tabela_pequena_tem_confianca_baixa(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Exemplo motivador da issue: n=4, N=1.000 tem margem ~48,9pp -> BAIXA."""
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[
                ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True)
            ],
            tamanho_amostra=4,
            total_linhas=1_000,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.BAIXA

    def test_nivel_de_confianca_nao_depende_da_proporcao_observada_por_coluna(
        self,
        tipo_integer: TipoDeDado,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Colunas com percentual_nulo bem diferentes têm o mesmo nível.

        Prova que o nível vem só de tamanho_amostra/total_linhas (fórmula
        conservadora, p=0,5 fixo) — evita o colapso que a proporção
        observada causaria numa coluna PK/UNIQUE (percentual_unico=100%
        zera a variância p(1-p) pra qualquer tamanho de amostra).
        """
        tabela = _tabela_curada_com_amostra(
            "clientes",
            colunas=[
                ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True),
                ColunaCurada(nome="obs", tipo_dado=tipo_varchar),
            ],
            tamanho_amostra=4,
            total_linhas=1_000,
        )
        contexto = construir_contexto([tabela])
        contexto.analisado.tabelas[0].colunas[0].metricas.append(
            _metrica(percentual_nulo=0.0)
        )
        contexto.analisado.tabelas[0].colunas[1].metricas.append(
            _metrica(percentual_nulo=100.0)
        )

        resultado = AnalisadorDeMetricasDeTabela()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica_confianca = resultado.valor.analisado.tabelas[0].metricas[1]
        assert isinstance(metrica_confianca, MetricasDeConfianca)
        assert metrica_confianca.nivel == NivelDeConfianca.BAIXA

"""Testes de AnalisadorDeMetricasDeColuna."""

import uuid
from collections.abc import Callable

import polars as pl
import pytest

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ContextoDeAnalise,
    MetricasBaseColuna,
)
from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import BancoCurado, ColunaCurada, TabelaCurada
from ddf.domain.ports.analisador import Analisador
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_coluna import (
    AnalisadorDeMetricasDeColuna,
)
from ddf.infrastructure.adapters.analyzers.comum.detector_de_formato import (
    TETO_SUBAMOSTRA,
    detectar_formato,
)


def _tabela_curada(
    *, colunas: list[ColunaCurada], amostra: pl.DataFrame | None, tamanho_amostra: int
) -> TabelaCurada:
    return TabelaCurada(
        nome_tabela="clientes",
        nome_escopo="public",
        colunas=colunas,
        total_linhas=tamanho_amostra,
        amostra=amostra,
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=tamanho_amostra
        ),
    )


def _metrica_de(coluna_analisada_metricas: list[object]) -> MetricasBaseColuna:
    metrica = coluna_analisada_metricas[0]
    assert isinstance(metrica, MetricasBaseColuna)
    return metrica


class TestFeliz:
    """Caminho feliz."""

    def test_analisador_de_metricas_de_coluna_satisfaz_analisador(
        self,
    ) -> None:
        """AnalisadorDeMetricasDeColuna conforma ao Port Analisador."""
        assert isinstance(AnalisadorDeMetricasDeColuna(), Analisador)

    def test_calcula_metricas_e_detecta_email_com_subdominio(
        self,
        tipo_varchar: TipoDeDado,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """métricas calculadas e e-mail com subdomínio detectado."""
        emails = [f"user{i}@mail.empresa.com.br" for i in range(150)]
        tabela = _tabela_curada(
            colunas=[
                ColunaCurada(nome="id", tipo_dado=tipo_integer, chave_primaria=True),
                ColunaCurada(nome="email", tipo_dado=tipo_varchar),
            ],
            amostra=pl.DataFrame({"id": list(range(150)), "email": emails}),
            tamanho_amostra=150,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []
        coluna_email = resultado.valor.analisado.tabelas[0].colunas[1]
        metrica = _metrica_de(coluna_email.metricas)
        assert metrica.formato_detectado == "email"
        assert metrica.percentual_nulo == 0.0
        assert metrica.percentual_unico == 100.0

    def test_libera_amostra_apos_processar_tabela(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Amostra é liberada (None) após a tabela ser processada."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"id": list(range(100))}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.curado.tabelas[0].amostra is None


class TestErro:
    """Erro esperado."""

    def test_curado_e_analisado_fora_de_sincronia_retorna_falha(
        self,
        tipo_integer: TipoDeDado,
    ) -> None:
        """Quantidade de tabelas diferente entre curado e analisado."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"id": [1]}),
            tamanho_amostra=1,
        )
        contexto = ContextoDeAnalise(
            curado=BancoCurado(tabelas=[tabela]),
            analisado=BancoAnalisado(tabelas=[]),
        )

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Falha)
        assert "inconsistente" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_tamanho_amostra_zero_nao_divide_por_zero(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """tamanho_amostra=0 (amostra ausente) não levanta ZeroDivisionError."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=None,
            tamanho_amostra=0,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 0.0
        assert metrica.percentual_unico == 0.0
        assert metrica.valores_frequentes == []
        assert metrica.minimo is None

    def test_coluna_inteiramente_nula(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna com todos os valores nulos não tem mínimo/máximo."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="valor", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"valor": [None] * 100}, schema={"valor": pl.Int64}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 100.0
        assert metrica.minimo is None
        assert metrica.maximo is None
        assert metrica.valores_frequentes == []

    def test_percentual_nulo_intermediario(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """percentual_nulo intermediário (30/100), não só os extremos 0%/100%."""
        valores: list[int | None] = [None] * 30 + list(range(70))
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="valor", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"valor": valores}, schema={"valor": pl.Int64}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 30.0

    def test_amostra_presente_mas_vazia_diverge_de_tamanho_amostra_positivo(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Amostra com 0 linhas mas metadados_amostra.tamanho_amostra > 0.

        Divergência upstream (ex.: bug de sampling gravando metadados errados) não
        deve produzir métrica factualmente errada (ex.: percentual_nulo=0.0 como
        se a amostra tivesse dado real) — trata como amostra vazia.
        """
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="valor", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"valor": []}, schema={"valor": pl.Int64}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 0.0
        assert metrica.percentual_unico == 0.0
        assert metrica.valores_frequentes == []

    def test_percentual_unico_e_valores_frequentes_excluem_nulos(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Nulos não contam como categoria em percentual_unico/valores_frequentes."""
        valores = [1, 1, None] + [None] * 97
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="valor", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"valor": valores}, schema={"valor": pl.Int64}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_unico == 1.0  # 1 valor distinto (o "1") / 100
        assert metrica.valores_frequentes == [("1", 2)]

    def test_amostra_pequena_emite_aviso_com_origem_correta(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """tamanho_amostra < 100 emite Aviso identificando a coluna."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"id": list(range(50))}),
            tamanho_amostra=50,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert resultado.avisos[0].origem == "AnalisadorDeMetricasDeColuna"
        assert "public.clientes.id" in resultado.avisos[0].mensagem

    def test_valores_frequentes_desempate_por_valor_crescente(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Valores empatados em contagem aparecem em ordem alfabética."""
        valores = ["b", "b", "a", "a", "c"] + [f"x{i}" for i in range(95)]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="letra", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"letra": valores}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.valores_frequentes[0] == ("a", 2)
        assert metrica.valores_frequentes[1] == ("b", 2)

    def test_coluna_varchar_com_poucos_nao_nulos_nao_aciona_formato(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """<20 valores não-nulos não aciona formato_detectado, mesmo a 100%."""
        emails = [f"user{i}@empresa.com" for i in range(10)] + [None] * 90
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.formato_detectado is None

    def test_coluna_float_trata_nan_como_nulo(
        self,
        tipo_float: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """NaN em coluna FLOAT conta como nulo, não como valor distinto.

        Regressão do achado da banca de revisão: sem normalizar NaN->null antes
        do cálculo, o Polars trata NaN como categoria própria em n_unique() e
        value_counts(), diferente de null — inflando percentual_unico e
        poluindo valores_frequentes com uma entrada 'NaN' fantasma.
        """
        valores = [10.5, float("nan"), None, 20.0, 20.0] + [None] * 95
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="preco", tipo_dado=tipo_float)],
            amostra=pl.DataFrame({"preco": valores}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 97.0  # 1 None explícito + 1 NaN + 95 None
        assert metrica.percentual_unico == 2.0  # 10.5 e 20.0, sem contar NaN
        assert metrica.valores_frequentes == [("20.0", 2), ("10.5", 1)]
        assert metrica.minimo == "10.5"
        assert metrica.maximo == "20.0"

    def test_coluna_dtype_object_nao_derruba_analisador(
        self,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna de dtype Object (ex.: uuid.UUID vindo do driver) não quebra.

        Regressão do achado da banca de revisão: `pl.Series.min()`/`.max()`/
        `.n_unique()` levantam InvalidOperationError em dtype `object` — dtype
        que o Polars usa como fallback pra tipos Python que não mapeia
        nativamente, como `uuid.UUID` retornado por drivers pra colunas UUID.
        Isso derrubava o Analisador inteiro por causa de uma única coluna.
        """
        tipo_uuid = TipoDeDado(categoria=CategoriaDeDado.UUID)
        ids = [uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=1)]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="rowguid", tipo_dado=tipo_uuid)],
            amostra=pl.DataFrame({"rowguid": ids}),
            tamanho_amostra=3,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.percentual_nulo == 0.0
        assert metrica.percentual_unico == pytest.approx(200 / 3)
        assert metrica.minimo == str(min(ids))
        assert metrica.maximo == str(max(ids))

    def test_coluna_binaria_nao_vira_endereco_de_memoria(
        self,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna binária (ex.: bytea/memoryview) não vira '<memory at 0x...>'.

        Regressão: `psycopg2` devolve `memoryview` pra colunas `bytea`, também
        dtype Object no Polars. `str()` puro sobre `memoryview` produz um
        endereço de memória (`<memory at 0x7f...>`), que não comunica nada sobre
        o dado e muda a cada execução — inútil num artefato versionado em Git.
        """
        tipo_desconhecido = TipoDeDado(categoria=CategoriaDeDado.UNKNOWN)
        valores = [memoryview(b"\x01\x02\x03"), memoryview(b"\x04\x05"), None]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="spatiallocation", tipo_dado=tipo_desconhecido)],
            amostra=pl.DataFrame({"spatiallocation": valores}),
            tamanho_amostra=3,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.minimo is not None
        assert "memory at" not in metrica.minimo
        assert "bytes" in metrica.minimo

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
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"id": list(range(100))}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        assert resultado.valor is not contexto
        assert contexto.analisado.tabelas[0].colunas[0].metricas == []
        assert contexto.curado.tabelas[0].amostra is not None

    def test_amostra_grande_ativa_subamostragem_mas_ainda_detecta_formato(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """>2000 não-nulos aciona sub-amostragem; formato ainda é detectado.

        Acima de `TETO_SUBAMOSTRA`, a decisão passa a rodar sobre uma
        sub-amostra determinística — com 100% dos valores sendo e-mail
        válido, o resultado não pode mudar.
        """
        emails = [f"user{i}@empresa.com" for i in range(5000)]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails}),
            tamanho_amostra=5000,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.formato_detectado == "email"

    def test_amostra_no_teto_mantem_comportamento_inalterado(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Exatamente no teto de sub-amostragem, roda sobre a população inteira.

        `TETO_SUBAMOSTRA` só ativa quando o nº de não-nulos EXCEDE o teto —
        no teto exato, o comportamento é o mesmo de uma amostra pequena.
        """
        emails = [f"user{i}@empresa.com" for i in range(TETO_SUBAMOSTRA)]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails}),
            tamanho_amostra=TETO_SUBAMOSTRA,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.formato_detectado == "email"

    def test_subamostragem_de_formato_e_deterministica_entre_execucoes(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Mesma amostra grande produz o mesmo formato_detectado em execuções repetidas.

        Seed fixo (`_SEED_SUBAMOSTRA_FORMATO`) garante reprodutibilidade —
        sem isso, `formato_detectado` poderia variar entre rodadas na
        mesma tabela sem nenhuma mudança de dado real.
        """
        valores = [f"user{i}@empresa.com" for i in range(4000)] + [
            f"texto livre numero {i}" for i in range(1000)
        ]
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": valores}),
            tamanho_amostra=5000,
        )

        resultado_1 = AnalisadorDeMetricasDeColuna()(construir_contexto([tabela]))
        resultado_2 = AnalisadorDeMetricasDeColuna()(construir_contexto([tabela]))

        assert isinstance(resultado_1, Sucesso)
        assert isinstance(resultado_2, Sucesso)
        metrica_1 = _metrica_de(
            resultado_1.valor.analisado.tabelas[0].colunas[0].metricas
        )
        metrica_2 = _metrica_de(
            resultado_2.valor.analisado.tabelas[0].colunas[0].metricas
        )
        assert metrica_1.formato_detectado == metrica_2.formato_detectado

    def test_subamostragem_preserva_decisao_longe_do_limiar(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Proporção de match bem acima/abaixo do threshold não vira flip.

        O seed fixo torna o resultado 100% determinístico mesmo perto da
        fronteira — não há nada "flaky" em testar ali. O que não dá é
        prever *analiticamente* o ponto exato de divergência entre a
        decisão da sub-amostra e a decisão que a população inteira daria
        (só empiricamente, rodando o código — ver
        `test_subamostragem_diverge_da_populacao_dentro_da_margem_de_erro`
        para um caso onde essa divergência acontece de fato). Este teste
        cobre os casos não-ambíguos, distantes da fronteira (90% e 65%),
        que são a maioria na prática.
        """
        emails_90pct = [f"user{i}@empresa.com" for i in range(9000)] + [
            f"texto livre {i}" for i in range(1000)
        ]
        tabela_90pct = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails_90pct}),
            tamanho_amostra=10000,
        )
        emails_65pct = [f"user{i}@empresa.com" for i in range(6500)] + [
            f"texto livre {i}" for i in range(3500)
        ]
        tabela_65pct = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails_65pct}),
            tamanho_amostra=10000,
        )

        resultado_90pct = AnalisadorDeMetricasDeColuna()(
            construir_contexto([tabela_90pct])
        )
        resultado_65pct = AnalisadorDeMetricasDeColuna()(
            construir_contexto([tabela_65pct])
        )

        assert isinstance(resultado_90pct, Sucesso)
        assert isinstance(resultado_65pct, Sucesso)
        metrica_90pct = _metrica_de(
            resultado_90pct.valor.analisado.tabelas[0].colunas[0].metricas
        )
        metrica_65pct = _metrica_de(
            resultado_65pct.valor.analisado.tabelas[0].colunas[0].metricas
        )
        assert metrica_90pct.formato_detectado == "email"
        assert metrica_65pct.formato_detectado is None

    def test_subamostragem_diverge_da_populacao_dentro_da_margem_de_erro(
        self,
        tipo_varchar: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Divergência real entre sub-amostra e população, dentro da margem esperada.

        Com 80.5% de match na população (dentro da margem de ±1.75% ao
        redor do threshold de 80% que `TETO_SUBAMOSTRA` documenta), a
        população inteira decidiria "email" (>= 80%), mas a sub-amostra de
        2000 valores (com o seed fixo do projeto) decide `None`. Essa
        divergência é esperada e aceita — é exatamente o custo estatístico
        que a sub-amostragem assume, não uma regressão a evitar. Trava o
        comportamento atual como referência, em vez de fingir que ele não
        existe (ver correção de docstring em
        `test_subamostragem_preserva_decisao_longe_do_limiar`).
        """
        emails = [f"user{i}@empresa.com" for i in range(8050)] + [
            f"texto livre {i}" for i in range(1950)
        ]
        assert detectar_formato([str(v) for v in emails]) == "email"

        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="email", tipo_dado=tipo_varchar)],
            amostra=pl.DataFrame({"email": emails}),
            tamanho_amostra=10000,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.formato_detectado is None

    def test_coluna_integer_nunca_tenta_detectar_formato(
        self,
        tipo_integer: TipoDeDado,
        construir_contexto: Callable[[list[TabelaCurada]], ContextoDeAnalise],
    ) -> None:
        """Coluna INTEGER nunca aciona detecção de formato, mesmo com 100 linhas."""
        tabela = _tabela_curada(
            colunas=[ColunaCurada(nome="id", tipo_dado=tipo_integer)],
            amostra=pl.DataFrame({"id": list(range(100))}),
            tamanho_amostra=100,
        )
        contexto = construir_contexto([tabela])

        resultado = AnalisadorDeMetricasDeColuna()(contexto)

        assert isinstance(resultado, Sucesso)
        metrica = _metrica_de(resultado.valor.analisado.tabelas[0].colunas[0].metricas)
        assert metrica.formato_detectado is None

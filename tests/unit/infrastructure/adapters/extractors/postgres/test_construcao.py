"""Testes de particoes_de_blocos/montar_metadados_do_schema/montar_consulta_amostra."""

from psycopg2 import sql

from ddf.domain.model.common.requisicao_de_amostragem import (
    AmostragemIntegral,
    AmostragemProbabilistica,
    RequisicaoPorFaixa,
)
from ddf.infrastructure.adapters.extractors.postgres._construcao import (
    montar_consulta_amostra,
    montar_metadados_do_schema,
    particoes_de_blocos,
)


def _texto_dos_fragmentos_sql(consulta: sql.Composed) -> str:
    """Extrai só os fragmentos `sql.SQL` (texto fixo) de um `Composed`.

    `Identifier`/`Literal` exigem uma conexão real pra `as_string()`
    (fazem quoting via o driver) — os fragmentos `SQL` puros não, então dá
    pra inspecionar a forma da query (ex.: "tem TABLESAMPLE?") sem precisar
    de um Postgres real.
    """
    return " ".join(
        parte.string for parte in consulta.seq if isinstance(parte, sql.SQL)
    )


class TestFeliz:
    """Caminho feliz."""

    def test_divide_em_faixas_do_mesmo_tamanho(self) -> None:
        """1000 blocos em 4 faixas -> 250 blocos cada, contíguas."""
        faixas = particoes_de_blocos(total_blocos=1000, n=4)

        assert faixas == [(0, 250), (250, 500), (500, 750), (750, None)]

    def test_ultima_faixa_nao_tem_teto(self) -> None:
        """A última faixa é sempre aberta (fim=None), nunca fechada."""
        faixas = particoes_de_blocos(total_blocos=100, n=2)

        assert faixas[-1][1] is None

    def test_montar_metadados_do_schema_agrupa_por_tabela(self) -> None:
        """PK, FK simples, total_linhas e largura ficam sob a tabela certa."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[
                ("pedidos", "id", "int4", None, None, None, None, "NO"),
                ("pedidos", "cliente_id", "int4", None, None, None, None, "NO"),
            ],
            linhas_pks=[("pedidos", "id")],
            linhas_fks=[
                ("pedidos", "cliente_id", "public", "clientes", "id", "fk_cliente")
            ],
            linhas_unicas=[],
            linhas_total_linhas=[("pedidos", 42.0)],
            linhas_largura_media=[("pedidos", 120)],
            linhas_comprimiveis=[],
            linhas_particionadas=[],
        )

        assert metadados.pks_por_tabela == {"pedidos": {"id"}}
        assert metadados.total_linhas_por_tabela == {"pedidos": 42}
        assert metadados.largura_media_por_tabela == {"pedidos": 120}
        assert [linha.nome for linha in metadados.colunas_por_tabela["pedidos"]] == [
            "id",
            "cliente_id",
        ]

    def test_montar_consulta_amostra_amostragem_integral_seleciona_tabela_inteira(
        self,
    ) -> None:
        """AmostragemIntegral vira SELECT * sem TABLESAMPLE nem seed."""
        consulta, requisicao_efetiva = montar_consulta_amostra(
            "public", "pedidos", AmostragemIntegral()
        )

        assert "TABLESAMPLE" not in _texto_dos_fragmentos_sql(consulta)
        assert requisicao_efetiva == AmostragemIntegral()

    def test_montar_consulta_amostra_por_faixa_usa_tablesample_system(self) -> None:
        """RequisicaoPorFaixa usa TABLESAMPLE SYSTEM, não BERNOULLI."""
        consulta, requisicao_efetiva = montar_consulta_amostra(
            "public",
            "pedidos",
            RequisicaoPorFaixa(percentual=10.0, seed=42),
        )

        assert "TABLESAMPLE SYSTEM" in _texto_dos_fragmentos_sql(consulta)
        assert requisicao_efetiva == RequisicaoPorFaixa(percentual=10.0, seed=42)


class TestBorda:
    """Casos de borda."""

    def test_n_igual_a_um_devolve_faixa_unica_aberta(self) -> None:
        """Sem paralelismo de verdade — 1 faixa cobrindo tudo."""
        faixas = particoes_de_blocos(total_blocos=500, n=1)

        assert faixas == [(0, None)]

    def test_tabela_vazia_ainda_gera_faixas_validas(self) -> None:
        """0 blocos não deve gerar faixas degeneradas (início > fim)."""
        faixas = particoes_de_blocos(total_blocos=0, n=3)

        assert faixas == [(0, 1), (1, 2), (2, None)]

    def test_n_maior_que_total_de_blocos_ainda_e_disjunto_e_exaustivo(self) -> None:
        """Mais faixas pedidas do que blocos existentes — sem overlap nem gap."""
        faixas = particoes_de_blocos(total_blocos=3, n=10)

        inicios_e_fins = [(inicio, fim) for inicio, fim in faixas[:-1]]
        assert all(fim - inicio >= 1 for inicio, fim in inicios_e_fins)
        # Disjunto: cada faixa começa exatamente onde a anterior termina.
        for (_, fim_anterior), (inicio_atual, _) in zip(faixas, faixas[1:]):
            assert fim_anterior == inicio_atual

    def test_resto_da_divisao_fica_todo_na_ultima_faixa(self) -> None:
        """total_blocos não múltiplo de n — a sobra vai pra faixa aberta final."""
        faixas = particoes_de_blocos(total_blocos=10, n=3)

        assert faixas == [(0, 3), (3, 6), (6, None)]

    def test_montar_metadados_indice_com_duas_colunas_vira_restricao_composta(
        self,
    ) -> None:
        """Mesmo indexrelid com 2 colunas vira RestricaoUnica, não coluna única."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[
                ("pedidos", "a", "int4", None, None, None, None, "NO"),
                ("pedidos", "b", "int4", None, None, None, None, "NO"),
            ],
            linhas_pks=[],
            linhas_fks=[],
            linhas_unicas=[("pedidos", 111, "a"), ("pedidos", 111, "b")],
            linhas_total_linhas=[],
            linhas_largura_media=[],
            linhas_comprimiveis=[],
            linhas_particionadas=[],
        )

        assert metadados.unicas_por_tabela.get("pedidos", set()) == set()
        restricoes = metadados.restricoes_unicas_por_tabela["pedidos"]
        assert len(restricoes) == 1
        assert restricoes[0].colunas == ("a", "b")

    def test_montar_metadados_total_linhas_negativo_vira_zero(self) -> None:
        """reltuples=-1 (nunca analisada) não pode virar total_linhas negativo."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[],
            linhas_pks=[],
            linhas_fks=[],
            linhas_unicas=[],
            linhas_total_linhas=[("pedidos", -1.0)],
            linhas_largura_media=[],
            linhas_comprimiveis=[],
            linhas_particionadas=[],
        )

        assert metadados.total_linhas_por_tabela == {"pedidos": 0}

    def test_montar_metadados_largura_media_zero_usa_padrao(self) -> None:
        """soma_avg_width == 0 (sem estatística real) cai pro padrão, não fica 0."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[],
            linhas_pks=[],
            linhas_fks=[],
            linhas_unicas=[],
            linhas_total_linhas=[],
            linhas_largura_media=[("pedidos", 0)],
            linhas_comprimiveis=[],
            linhas_particionadas=[],
        )

        assert metadados.largura_media_por_tabela["pedidos"] > 0

    def test_montar_consulta_amostra_probabilistica_sem_seed_gera_um(self) -> None:
        """AmostragemProbabilistica sem seed explícito recebe um sorteado."""
        _, requisicao_efetiva = montar_consulta_amostra(
            "public",
            "pedidos",
            AmostragemProbabilistica(percentual=10.0, seed=None),
        )

        assert isinstance(requisicao_efetiva, AmostragemProbabilistica)
        assert requisicao_efetiva.seed is not None


class TestErro:
    """Uso indevido."""

    def test_n_zero_ou_negativo_devolve_lista_vazia(self) -> None:
        """`n <= 0` não faz sentido como número de faixas — devolve vazio."""
        assert particoes_de_blocos(total_blocos=100, n=0) == []
        assert particoes_de_blocos(total_blocos=100, n=-1) == []

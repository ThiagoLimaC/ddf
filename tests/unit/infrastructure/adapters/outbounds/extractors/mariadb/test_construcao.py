"""Testes diretos das funções puras de _construcao.py.

As demais funções deste módulo (_construir_coluna,
_promover_booleanos_pela_amostra, _particionar_colunas_unicas,
_agrupar_colunas_unicas_por_tabela, _colunas_json_de_check_clauses,
_agrupar_colunas_json_por_tabela) já têm cobertura substancial e realista via
ExtratorMariaDB.extrair_tabela em test_extrator_mariadb.py — este arquivo
cobre só o que não tinha nenhum teste, direto ou indireto, antes do split.
"""

from ddf.infrastructure.adapters.outbounds.extractors.mariadb._construcao import (
    _elegibilidade_de_pk_para_faixa,
    _LinhaColuna,
    _PkElegivel,
    _PkNaoElegivel,
    _quotar_identificador,
    montar_metadados_do_schema,
    particionar_faixas_exaustivas,
)


def _linha_coluna(nome: str, data_type: str) -> _LinhaColuna:
    """Constrói uma _LinhaColuna mínima, só com os campos relevantes ao teste."""
    return _LinhaColuna(
        nome=nome,
        data_type=data_type,
        column_type=data_type,
        tamanho_maximo=None,
        precisao=None,
        escala=None,
        precisao_fracionaria=None,
        is_nullable="NO",
    )


class TestFeliz:
    """Caminho feliz."""

    def test_pk_unica_e_inteira_e_elegivel(self) -> None:
        """PK de coluna única e tipo bigint é elegível para amostragem por faixa."""
        resultado = _elegibilidade_de_pk_para_faixa(
            colunas_pk={"id"},
            linhas_colunas=[_linha_coluna("id", "bigint")],
        )

        assert resultado == _PkElegivel(nome_coluna="id")

    def test_divide_dominio_em_faixas_do_mesmo_tamanho(self) -> None:
        """PK de 1 a 1000 em 4 faixas -> 250 valores cada, contíguas."""
        faixas = particionar_faixas_exaustivas(minimo=1, maximo=1000, n=4)

        assert faixas == [(1, 251), (251, 501), (501, 751), (751, None)]

    def test_ultima_faixa_nao_tem_teto(self) -> None:
        """A última faixa é sempre aberta (fim=None), nunca fechada."""
        faixas = particionar_faixas_exaustivas(minimo=1, maximo=100, n=2)

        assert faixas[-1][1] is None

    def test_montar_metadados_do_schema_agrupa_por_tabela(self) -> None:
        """PK, FK simples, JSON e total_linhas/largura ficam sob a tabela certa."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[
                ("pedidos", "id", "int", "int", None, None, None, None, "NO"),
                (
                    "pedidos",
                    "dados",
                    "longtext",
                    "longtext",
                    None,
                    None,
                    None,
                    None,
                    "NO",
                ),
            ],
            linhas_pks=[("pedidos", "id")],
            linhas_fks=[
                ("pedidos", "cliente_id", "vendas", "clientes", "id", "fk_cliente")
            ],
            linhas_unicas=[],
            linhas_json=[("pedidos", "json_valid(`dados`)")],
            linhas_total_linhas=[("pedidos", 42.0, 120)],
        )

        assert metadados.pks_por_tabela == {"pedidos": {"id"}}
        assert metadados.total_linhas_por_tabela == {"pedidos": 42}
        assert metadados.largura_media_por_tabela == {"pedidos": 120}
        assert metadados.colunas_json_por_tabela["pedidos"] == {"dados"}


class TestBorda:
    """Bordas."""

    def test_identificador_com_crase_e_escapado_com_crase_duplicada(self) -> None:
        """Crase literal no nome vira crase duplicada, sem quebrar o SQL."""
        assert _quotar_identificador("tabela`maliciosa") == "`tabela``maliciosa`"

    def test_identificador_sem_caractere_especial_so_e_envolto_em_crases(
        self,
    ) -> None:
        """Nome comum não sofre nenhuma substituição, só recebe as crases."""
        assert _quotar_identificador("clientes") == "`clientes`"

    def test_tabela_sem_pk_nao_e_elegivel(self) -> None:
        """Sem chave primária, não há coluna pra cortar em faixas."""
        resultado = _elegibilidade_de_pk_para_faixa(
            colunas_pk=set(),
            linhas_colunas=[_linha_coluna("id", "bigint")],
        )

        assert resultado == _PkNaoElegivel(motivo="tabela sem chave primária")

    def test_pk_composta_nao_e_elegivel(self) -> None:
        """PK de 2+ colunas não define um único corte linear."""
        resultado = _elegibilidade_de_pk_para_faixa(
            colunas_pk={"pais_id", "filial_id"},
            linhas_colunas=[
                _linha_coluna("pais_id", "int"),
                _linha_coluna("filial_id", "int"),
            ],
        )

        assert resultado == _PkNaoElegivel(motivo="chave primária composta")

    def test_pk_nao_inteira_nao_e_elegivel(self) -> None:
        """PK do tipo char (ex.: UUID armazenado como texto) não serve pro corte."""
        resultado = _elegibilidade_de_pk_para_faixa(
            colunas_pk={"id"},
            linhas_colunas=[_linha_coluna("id", "char")],
        )

        assert resultado == _PkNaoElegivel(
            motivo="chave primária 'id' não é de tipo inteiro"
        )

    def test_tinyint_e_elegivel_mesmo_sendo_candidato_a_booleano(self) -> None:
        """Elegibilidade usa o data_type cru — promoção a BOOLEAN não entra aqui."""
        resultado = _elegibilidade_de_pk_para_faixa(
            colunas_pk={"id"},
            linhas_colunas=[_linha_coluna("id", "tinyint")],
        )

        assert resultado == _PkElegivel(nome_coluna="id")

    def test_n_igual_a_um_devolve_faixa_unica_aberta(self) -> None:
        """Sem paralelismo de verdade — 1 faixa cobrindo o domínio inteiro."""
        faixas = particionar_faixas_exaustivas(minimo=1, maximo=500, n=1)

        assert faixas == [(1, None)]

    def test_tabela_com_uma_linha_ainda_gera_faixas_validas(self) -> None:
        """`min == max` (uma linha só) não deve gerar faixas degeneradas."""
        faixas = particionar_faixas_exaustivas(minimo=7, maximo=7, n=3)

        assert faixas == [(7, 8), (8, 9), (9, None)]

    def test_n_maior_que_dominio_ainda_e_disjunto_e_exaustivo(self) -> None:
        """Mais faixas pedidas do que valores de PK existentes — sem overlap nem gap."""
        faixas = particionar_faixas_exaustivas(minimo=1, maximo=3, n=10)

        for inicio, fim in faixas[:-1]:
            assert fim is not None
            assert fim - inicio >= 1
        for (_, fim_anterior), (inicio_atual, _) in zip(faixas, faixas[1:]):
            assert fim_anterior == inicio_atual

    def test_resto_da_divisao_fica_todo_na_ultima_faixa(self) -> None:
        """Domínio não múltiplo de n — a sobra vai pra faixa aberta final."""
        faixas = particionar_faixas_exaustivas(minimo=0, maximo=9, n=3)

        assert faixas == [(0, 3), (3, 6), (6, None)]

    def test_pk_nao_comecando_em_zero_preserva_offset(self) -> None:
        """Domínio deslocado (PK não começa em 0) não distorce o tamanho das faixas."""
        faixas = particionar_faixas_exaustivas(minimo=1000, maximo=1999, n=2)

        assert faixas == [(1000, 1500), (1500, None)]

    def test_montar_metadados_linhas_estimadas_none_vira_zero(self) -> None:
        """`linhas_estimadas is None` (tabela nunca analisada) não quebra o round."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[],
            linhas_pks=[],
            linhas_fks=[],
            linhas_unicas=[],
            linhas_json=[],
            linhas_total_linhas=[("pedidos", None, 120)],
        )

        assert metadados.total_linhas_por_tabela == {"pedidos": 0}

    def test_montar_metadados_largura_media_none_usa_padrao(self) -> None:
        """largura_media None/0 (sem estatística real) cai pro padrão, não fica 0."""
        metadados = montar_metadados_do_schema(
            linhas_colunas=[],
            linhas_pks=[],
            linhas_fks=[],
            linhas_unicas=[],
            linhas_json=[],
            linhas_total_linhas=[("pedidos", 10.0, None)],
        )

        assert metadados.largura_media_por_tabela["pedidos"] > 0


class TestErro:
    """Uso indevido."""

    def test_n_zero_ou_negativo_devolve_lista_vazia(self) -> None:
        """`n <= 0` não faz sentido como número de faixas — devolve vazio."""
        assert particionar_faixas_exaustivas(minimo=1, maximo=100, n=0) == []
        assert particionar_faixas_exaustivas(minimo=1, maximo=100, n=-1) == []

"""Testes diretos das funções puras de _construcao.py.

As demais funções deste módulo (_construir_coluna,
_promover_booleanos_pela_amostra, _particionar_colunas_unicas,
_agrupar_colunas_unicas_por_tabela, _colunas_json_de_check_clauses,
_agrupar_colunas_json_por_tabela) já têm cobertura substancial e realista via
ExtratorMariaDB.extrair_tabela em test_extrator_mariadb.py — este arquivo
cobre só o que não tinha nenhum teste, direto ou indireto, antes do split.
"""

from ddf.infrastructure.adapters.extractors.mariadb._construcao import (
    _elegibilidade_de_pk_para_faixa,
    _LinhaColuna,
    _PkElegivel,
    _PkNaoElegivel,
    _quotar_identificador,
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

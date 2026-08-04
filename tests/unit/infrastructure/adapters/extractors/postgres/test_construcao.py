"""Testes diretos das funções puras de _construcao.py.

_construir_coluna já tem cobertura substancial e realista via
ExtratorPostgres.extrair_tabela em test_extrator_postgres.py — este arquivo
cobre só _tabela_tem_coluna_toast_avel, que não tinha teste próprio.
"""

from ddf.infrastructure.adapters.extractors.postgres._construcao import (
    _LinhaColuna,
    _tabela_tem_coluna_toast_avel,
)


def _linha_coluna(nome: str, udt_name: str) -> _LinhaColuna:
    """Constrói uma _LinhaColuna mínima, só com os campos relevantes ao teste."""
    return _LinhaColuna(
        nome=nome,
        udt_name=udt_name,
        tamanho_maximo=None,
        precisao=None,
        escala=None,
        is_nullable="NO",
    )


class TestFeliz:
    """Caminho feliz."""

    def test_tabela_com_coluna_text_e_toast_avel(self) -> None:
        """`text` é um dos tipos sujeitos a compressão TOAST."""
        resultado = _tabela_tem_coluna_toast_avel(
            [_linha_coluna("id", "int4"), _linha_coluna("descricao", "text")]
        )

        assert resultado is True


class TestBorda:
    """Bordas."""

    def test_tabela_so_com_tipos_de_largura_fixa_nao_e_toast_avel(self) -> None:
        """Sem coluna comprimível, a estimativa de catálogo já é confiável."""
        resultado = _tabela_tem_coluna_toast_avel(
            [
                _linha_coluna("id", "int4"),
                _linha_coluna("ativo", "bool"),
                _linha_coluna("criado_em", "timestamp"),
            ]
        )

        assert resultado is False

    def test_lista_de_colunas_vazia_nao_e_toast_avel(self) -> None:
        """Sem colunas, não há o que sondar."""
        assert _tabela_tem_coluna_toast_avel([]) is False

    def test_jsonb_e_bytea_tambem_sao_toast_aveis(self) -> None:
        """Cobre os demais tipos da lista, não só text."""
        assert _tabela_tem_coluna_toast_avel([_linha_coluna("dados", "jsonb")])
        assert _tabela_tem_coluna_toast_avel([_linha_coluna("arquivo", "bytea")])

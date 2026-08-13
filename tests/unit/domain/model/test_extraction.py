"""Testes de ColunaExtraida e TabelaExtraida."""

import polars as pl
import pytest
from pydantic import ValidationError

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida


class TestFeliz:
    """Caminho feliz."""

    def test_cria_coluna_extraida_com_chave_estrangeira(
        self, tipo_integer: TipoDeDado
    ) -> None:
        """ColunaExtraida guarda referência de chave estrangeira."""
        coluna = ColunaExtraida(
            nome="cliente_id",
            tipo_dado=tipo_integer,
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
                )
            ],
        )

        assert coluna.chave_estrangeira is True
        assert coluna.referencias == [
            ReferenciaDeColuna(
                nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
            )
        ]

    def test_cria_coluna_extraida_com_fk_polimorfica(
        self, tipo_integer: TipoDeDado
    ) -> None:
        """ColunaExtraida guarda 2+ referências quando a FK é polimórfica."""
        coluna = ColunaExtraida(
            nome="entidade_id",
            tipo_dado=tipo_integer,
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="public", nome_tabela="fornecedores", nome_coluna="id"
                ),
            ],
        )

        assert len(coluna.referencias) == 2

    def test_cria_tabela_extraida_com_amostra(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """TabelaExtraida guarda colunas, amostra e metadados."""
        tabela = TabelaExtraida(
            nome_tabela="pedidos",
            nome_escopo="public",
            colunas=[
                ColunaExtraida(nome="id", tipo_dado=tipo_integer, chave_primaria=True)
            ],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
        )

        assert tabela.nome_tabela == "pedidos"
        assert tabela.amostra.height == 2

    def test_cria_tabela_extraida_com_restricao_unica_composta(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """TabelaExtraida guarda UNIQUE composto de colunas reais."""
        tabela = TabelaExtraida(
            nome_tabela="enderecos",
            nome_escopo="public",
            colunas=[
                ColunaExtraida(nome="codigo_pais", tipo_dado=tipo_integer),
                ColunaExtraida(nome="codigo_local", tipo_dado=tipo_integer),
            ],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
            restricoes_unicas=[RestricaoUnica(colunas=("codigo_pais", "codigo_local"))],
        )

        assert tabela.restricoes_unicas == [
            RestricaoUnica(colunas=("codigo_pais", "codigo_local"))
        ]

    def test_cria_tabela_extraida_com_restricao_fk_composta(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """TabelaExtraida guarda FK composta de colunas reais."""
        tabela = TabelaExtraida(
            nome_tabela="pedidos",
            nome_escopo="vendas",
            colunas=[
                ColunaExtraida(nome="pais_id", tipo_dado=tipo_integer),
                ColunaExtraida(nome="estado_id", tipo_dado=tipo_integer),
            ],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="geografia",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )

        assert tabela.restricoes_fk_compostas == [
            RestricaoDeFkComposta(
                colunas_locais=("pais_id", "estado_id"),
                nome_escopo_referenciado="geografia",
                nome_tabela_referenciada="estados",
                colunas_referenciadas=("pais_id", "id"),
            )
        ]


class TestErro:
    """Erro esperado."""

    def test_coluna_extraida_fk_sem_referencia_levanta_validation_error(
        self,
        tipo_integer: TipoDeDado,
    ) -> None:
        """chave_estrangeira=True sem tabela/coluna referenciada."""
        with pytest.raises(ValidationError, match="chave_estrangeira"):
            ColunaExtraida(
                nome="cliente_id", tipo_dado=tipo_integer, chave_estrangeira=True
            )

    def test_coluna_extraida_referencia_sem_fk_levanta_validation_error(
        self,
        tipo_integer: TipoDeDado,
    ) -> None:
        """referência preenchida sem chave_estrangeira=True."""
        with pytest.raises(ValidationError, match="chave_estrangeira"):
            ColunaExtraida(
                nome="cliente_id",
                tipo_dado=tipo_integer,
                referencias=[
                    ReferenciaDeColuna(
                        nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
                    )
                ],
            )

    def test_tabela_extraida_total_linhas_negativo_levanta_validation_error(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """total_linhas negativo é logicamente impossível."""
        with pytest.raises(ValidationError, match="total_linhas"):
            TabelaExtraida(
                nome_tabela="pedidos",
                nome_escopo="public",
                colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
                total_linhas=-1,
                amostra=amostra_df,
                metadados_amostra=metadados_de_amostra,
            )

    def test_tabela_extraida_com_colunas_duplicadas_levanta_validation_error(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """Dois nomes de coluna iguais na mesma tabela."""
        with pytest.raises(ValidationError, match="duplicados"):
            TabelaExtraida(
                nome_tabela="pedidos",
                nome_escopo="public",
                colunas=[
                    ColunaExtraida(nome="id", tipo_dado=tipo_integer),
                    ColunaExtraida(nome="id", tipo_dado=tipo_integer),
                ],
                total_linhas=10,
                amostra=amostra_df,
                metadados_amostra=metadados_de_amostra,
            )

    def test_tabela_extraida_sem_amostra_levanta_validation_error(
        self, tipo_integer: TipoDeDado, metadados_de_amostra: MetadadosDeAmostra
    ) -> None:
        """Amostra é obrigatória — só TabelaCurada admite None."""
        with pytest.raises(ValidationError):
            TabelaExtraida(
                nome_tabela="pedidos",
                nome_escopo="public",
                colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
                total_linhas=10,
                amostra=None,  # type: ignore[arg-type]
                metadados_amostra=metadados_de_amostra,
            )

    def test_tabela_extraida_restricao_unica_com_coluna_inexistente_e_invalida(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """RestricaoUnica citando coluna que a tabela não tem."""
        with pytest.raises(ValidationError, match="inexistente"):
            TabelaExtraida(
                nome_tabela="enderecos",
                nome_escopo="public",
                colunas=[ColunaExtraida(nome="codigo_pais", tipo_dado=tipo_integer)],
                total_linhas=10,
                amostra=amostra_df,
                metadados_amostra=metadados_de_amostra,
                restricoes_unicas=[
                    RestricaoUnica(colunas=("codigo_pais", "codigo_local"))
                ],
            )

    def test_tabela_extraida_restricao_fk_composta_com_coluna_inexistente_e_invalida(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """RestricaoDeFkComposta citando coluna local inexistente."""
        with pytest.raises(ValidationError, match="inexistente"):
            TabelaExtraida(
                nome_tabela="pedidos",
                nome_escopo="vendas",
                colunas=[ColunaExtraida(nome="pais_id", tipo_dado=tipo_integer)],
                total_linhas=10,
                amostra=amostra_df,
                metadados_amostra=metadados_de_amostra,
                restricoes_fk_compostas=[
                    RestricaoDeFkComposta(
                        colunas_locais=("pais_id", "estado_id"),
                        nome_escopo_referenciado="geografia",
                        nome_tabela_referenciada="estados",
                        colunas_referenciadas=("pais_id", "id"),
                    )
                ],
            )


class TestBorda:
    """Bordas."""

    def test_coluna_extraida_sem_chaves_usa_defaults(
        self, tipo_integer: TipoDeDado
    ) -> None:
        """Coluna comum, sem chave primária/estrangeira, usa defaults False/None."""
        coluna = ColunaExtraida(nome="descricao", tipo_dado=tipo_integer)

        assert coluna.chave_primaria is False
        assert coluna.chave_estrangeira is False
        assert coluna.referencias == []

    def test_tabela_extraida_sem_restricoes_unicas_usa_lista_vazia(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """Tabela sem nenhum UNIQUE composto tem restricoes_unicas == []."""
        tabela = TabelaExtraida(
            nome_tabela="pedidos",
            nome_escopo="public",
            colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
        )

        assert tabela.restricoes_unicas == []

    def test_tabela_extraida_sem_restricoes_fk_compostas_usa_lista_vazia(
        self,
        tipo_integer: TipoDeDado,
        metadados_de_amostra: MetadadosDeAmostra,
        amostra_df: pl.DataFrame,
    ) -> None:
        """Tabela sem nenhuma FK composta tem restricoes_fk_compostas == []."""
        tabela = TabelaExtraida(
            nome_tabela="pedidos",
            nome_escopo="public",
            colunas=[ColunaExtraida(nome="id", tipo_dado=tipo_integer)],
            total_linhas=10,
            amostra=amostra_df,
            metadados_amostra=metadados_de_amostra,
        )

        assert tabela.restricoes_fk_compostas == []

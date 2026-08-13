"""Testes de RestricaoDeFkComposta."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta


class TestFeliz:
    """Caminho feliz."""

    def test_restricao_de_fk_composta_guarda_colunas_em_ordem(self) -> None:
        """Guarda colunas locais e referenciadas na ordem informada."""
        restricao = RestricaoDeFkComposta(
            colunas_locais=("pais_id", "estado_id"),
            nome_escopo_referenciado="geografia",
            nome_tabela_referenciada="estados",
            colunas_referenciadas=("pais_id", "id"),
        )

        assert restricao.colunas_locais == ("pais_id", "estado_id")
        assert restricao.colunas_referenciadas == ("pais_id", "id")
        assert restricao.nome_escopo_referenciado == "geografia"
        assert restricao.nome_tabela_referenciada == "estados"

    def test_restricao_de_fk_composta_aceita_mais_de_duas_colunas(self) -> None:
        """Não limita o número de colunas a 2."""
        restricao = RestricaoDeFkComposta(
            colunas_locais=("a", "b", "c"),
            nome_escopo_referenciado="escopo",
            nome_tabela_referenciada="tabela",
            colunas_referenciadas=("x", "y", "z"),
        )

        assert restricao.colunas_locais == ("a", "b", "c")


class TestErro:
    """Erro esperado."""

    def test_uma_coluna_local_levanta_validation_error(self) -> None:
        """1 coluna não é composta — cabe em `ColunaExtraida.referencias`."""
        with pytest.raises(ValidationError, match="mínimo 2 colunas locais"):
            RestricaoDeFkComposta(
                colunas_locais=("id",),
                nome_escopo_referenciado="escopo",
                nome_tabela_referenciada="tabela",
                colunas_referenciadas=("id",),
            )

    def test_coluna_local_duplicada_levanta_validation_error(self) -> None:
        """Mesma coluna local repetida não é uma constraint válida."""
        with pytest.raises(ValidationError, match="duplicadas"):
            RestricaoDeFkComposta(
                colunas_locais=("codigo", "codigo"),
                nome_escopo_referenciado="escopo",
                nome_tabela_referenciada="tabela",
                colunas_referenciadas=("codigo", "codigo"),
            )

    def test_contagens_diferentes_levanta_validation_error(self) -> None:
        """Nº de colunas locais e referenciadas precisa ser igual."""
        with pytest.raises(ValidationError, match="mesmo número de colunas"):
            RestricaoDeFkComposta(
                colunas_locais=("a", "b"),
                nome_escopo_referenciado="escopo",
                nome_tabela_referenciada="tabela",
                colunas_referenciadas=("x",),
            )


class TestBorda:
    """Bordas."""

    def test_restricao_de_fk_composta_e_imutavel(self) -> None:
        """RestricaoDeFkComposta é imutável após construção (frozen=True)."""
        restricao = RestricaoDeFkComposta(
            colunas_locais=("a", "b"),
            nome_escopo_referenciado="escopo",
            nome_tabela_referenciada="tabela",
            colunas_referenciadas=("x", "y"),
        )

        with pytest.raises(ValidationError):
            restricao.colunas_locais = ("a", "c")

    def test_restricao_de_fk_composta_permite_colunas_referenciadas_duplicadas(
        self,
    ) -> None:
        """Colunas referenciadas podem repetir nome (tabela referenciada diferente).

        Só `colunas_locais` precisa ser sem duplicata — a mesma coluna local
        não pode aparecer duas vezes na constraint. As colunas do lado
        referenciado nomeando a mesma string que uma coluna local (ex. ambas
        chamadas "id") não é duplicata real, é coincidência de nome entre
        tabelas diferentes.
        """
        restricao = RestricaoDeFkComposta(
            colunas_locais=("pais_id", "estado_id"),
            nome_escopo_referenciado="geografia",
            nome_tabela_referenciada="estados",
            colunas_referenciadas=("id", "id"),
        )

        assert restricao.colunas_referenciadas == ("id", "id")

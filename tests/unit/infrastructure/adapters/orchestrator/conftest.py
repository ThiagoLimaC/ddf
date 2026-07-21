"""Fixtures compartilhadas dos testes de OrquestradorParalelo."""

from collections.abc import Callable

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import ColunaCurada, TabelaCurada
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


def _tabela_extraida(nome_escopo: str, nome_tabela: str) -> TabelaExtraida:
    """Constrói uma TabelaExtraida mínima (1 coluna) para os testes do Orquestrador."""
    return TabelaExtraida(
        nome_tabela=nome_tabela,
        nome_escopo=nome_escopo,
        colunas=[
            ColunaExtraida(
                nome="id",
                tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
                chave_primaria=True,
            )
        ],
        total_linhas=1,
        amostra=pl.DataFrame({"id": [1]}),
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=1
        ),
    )


@pytest.fixture
def fabrica_tabela_extraida() -> Callable[[str, str], TabelaExtraida]:
    """Expõe o builder de TabelaExtraida pros testes montarem fixtures próprias."""
    return _tabela_extraida


class ExtratorFake:
    """Extrator fake — listagem/extração configuráveis por teste, sem I/O real."""

    def __init__(
        self,
        tabelas_por_escopo: dict[str, Resultado[list[tuple[str, str]]]],
        falhas_de_extracao: dict[tuple[str, str], str] | None = None,
        excecoes_de_extracao: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        """Guarda as respostas fixas de listar_tabelas/extrair_tabela por chave.

        Args:
            tabelas_por_escopo: Resultado que listar_tabelas(escopo) devolve.
            falhas_de_extracao: mapeia (escopo, tabela) -> mensagem de erro;
                ausência da chave significa extração bem-sucedida.
            excecoes_de_extracao: mapeia (escopo, tabela) -> Exception a
                levantar em vez de retornar um Resultado — simula um bug
                não previsto no Extrator concreto (issue #56, boundary de
                exceção do OrquestradorParalelo).
        """
        self._tabelas_por_escopo = tabelas_por_escopo
        self._falhas_de_extracao = falhas_de_extracao or {}
        self._excecoes_de_extracao = excecoes_de_extracao or {}

    def listar_escopos(self) -> Resultado[list[str]]:
        """Não é exercitado pelos testes de OrquestradorParalelo — sem corpo real."""
        ...

    def listar_tabelas(self, escopo: str) -> Resultado[list[tuple[str, str]]]:
        """Devolve o Resultado pré-configurado para o escopo informado."""
        return self._tabelas_por_escopo[escopo]

    def extrair_tabela(self, escopo: str, tabela: str) -> Resultado[TabelaExtraida]:
        """Devolve a Falha/exceção pré-configurada, ou Sucesso com tabela mínima."""
        excecao = self._excecoes_de_extracao.get((escopo, tabela))
        if excecao is not None:
            raise excecao
        erro = self._falhas_de_extracao.get((escopo, tabela))
        if erro is not None:
            return Falha(erro)
        return Sucesso(_tabela_extraida(escopo, tabela))


class SobrescritaFake:
    """Sobrescrita fake — traduz TabelaExtraida em TabelaCurada, sem tocar disco."""

    def __init__(self, falhas: dict[tuple[str, str], str] | None = None) -> None:
        """Guarda as falhas pré-configuradas por (escopo, tabela).

        Args:
            falhas: mapeia (escopo, tabela) -> mensagem de erro; ausência da
                chave significa sobrescrita bem-sucedida.
        """
        self._falhas = falhas or {}

    def __call__(self, entrada: TabelaExtraida) -> Resultado[TabelaCurada]:
        """Traduz a TabelaExtraida em TabelaCurada, ou devolve a Falha configurada."""
        chave = (entrada.nome_escopo, entrada.nome_tabela)
        erro = self._falhas.get(chave)
        if erro is not None:
            return Falha(erro)

        colunas: list[ColunaCurada] = []
        for coluna in entrada.colunas:
            colunas.append(
                ColunaCurada(
                    nome=coluna.nome,
                    tipo_dado=coluna.tipo_dado,
                    chave_primaria=coluna.chave_primaria,
                    chave_estrangeira=coluna.chave_estrangeira,
                    referencia=coluna.referencia,
                )
            )
        return Sucesso(
            TabelaCurada(
                nome_tabela=entrada.nome_tabela,
                nome_escopo=entrada.nome_escopo,
                colunas=colunas,
                total_linhas=entrada.total_linhas,
                amostra=entrada.amostra,
                metadados_amostra=entrada.metadados_amostra,
            )
        )


@pytest.fixture
def construir_extrator_fake() -> Callable[..., ExtratorFake]:
    """Expõe o construtor de ExtratorFake como fixture."""

    def _construir(
        tabelas_por_escopo: dict[str, Resultado[list[tuple[str, str]]]],
        falhas_de_extracao: dict[tuple[str, str], str] | None = None,
        excecoes_de_extracao: dict[tuple[str, str], Exception] | None = None,
    ) -> ExtratorFake:
        return ExtratorFake(
            tabelas_por_escopo, falhas_de_extracao, excecoes_de_extracao
        )

    return _construir


@pytest.fixture
def construir_sobrescrita_fake() -> Callable[..., SobrescritaFake]:
    """Expõe o construtor de SobrescritaFake como fixture."""

    def _construir(
        falhas: dict[tuple[str, str], str] | None = None,
    ) -> SobrescritaFake:
        return SobrescritaFake(falhas)

    return _construir

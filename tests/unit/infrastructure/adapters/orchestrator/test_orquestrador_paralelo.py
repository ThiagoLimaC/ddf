"""Testes de OrquestradorParalelo."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import polars as pl
import pytest

from ddf.domain.model.common.metadados_de_amostra import MetadadosDeAmostra
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.curation import BancoCurado, ColunaCurada, TabelaCurada
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.orchestrator.orquestrador_paralelo import (
    OrquestradorParalelo,
)

if TYPE_CHECKING:
    from .conftest import ExtratorFake, SobrescritaFake


def _tabela_com_colunas(
    nome_escopo: str,
    nome_tabela: str,
    colunas: list[ColunaExtraida],
    restricoes_unicas: list[RestricaoUnica] | None = None,
    restricoes_fk_compostas: list[RestricaoDeFkComposta] | None = None,
) -> TabelaExtraida:
    """Constrói uma TabelaExtraida com colunas/restrições sob medida para o teste."""
    return TabelaExtraida(
        nome_tabela=nome_tabela,
        nome_escopo=nome_escopo,
        colunas=colunas,
        total_linhas=1,
        amostra=pl.DataFrame({coluna.nome: [1] for coluna in colunas}),
        metadados_amostra=MetadadosDeAmostra(
            estrategia="percentual_de_linhas", tamanho_amostra=1
        ),
        restricoes_unicas=restricoes_unicas or [],
        restricoes_fk_compostas=restricoes_fk_compostas or [],
    )


class TestFeliz:
    """Caminho feliz."""

    def test_extrair_lista_e_extrai_tabelas_ordenadas(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Extrai tabelas de múltiplos escopos, resultado ordenado."""
        extrator = construir_extrator_fake(
            {
                "vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")]),
                "estoque": Sucesso([("estoque", "produtos")]),
            }
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas", "estoque"], extrator)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []
        identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor]
        assert identificadores == [
            ("estoque", "produtos"),
            ("vendas", "clientes"),
            ("vendas", "pedidos"),
        ]

    def test_aplicar_sobrescritas_agrega_banco_curado_ordenado(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        construir_sobrescrita_fake: Callable[..., SobrescritaFake],
    ) -> None:
        """Aplica Sobrescrita em paralelo, BancoCurado ordenado."""
        tabelas = [
            fabrica_tabela_extraida("vendas", "pedidos"),
            fabrica_tabela_extraida("estoque", "produtos"),
            fabrica_tabela_extraida("vendas", "clientes"),
        ]
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.aplicar_sobrescritas(
            tabelas, construir_sobrescrita_fake()
        )

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []
        assert isinstance(resultado.valor, BancoCurado)
        identificadores = [
            (t.nome_escopo, t.nome_tabela) for t in resultado.valor.tabelas
        ]
        assert identificadores == [
            ("estoque", "produtos"),
            ("vendas", "clientes"),
            ("vendas", "pedidos"),
        ]

    def test_aplicar_sobrescritas_preserva_avisos_de_sucesso(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Aviso de uma Sobrescrita bem-sucedida não é descartado.

        Reproduz o caso real de SobrescritaDeTabela, que emite Aviso com o
        caminho do skeleton mesmo quando devolve Sucesso — sem isso, a etapa de
        geração de skeletons do wizard não teria nada pra exibir.
        """

        def _sobrescrita_com_aviso(tabela: TabelaExtraida) -> Resultado[TabelaCurada]:
            curada = TabelaCurada(
                nome_tabela=tabela.nome_tabela,
                nome_escopo=tabela.nome_escopo,
                colunas=[
                    ColunaCurada(
                        nome=coluna.nome,
                        tipo_dado=coluna.tipo_dado,
                        chave_primaria=coluna.chave_primaria,
                        chave_estrangeira=coluna.chave_estrangeira,
                        referencia=coluna.referencia,
                    )
                    for coluna in tabela.colunas
                ],
                total_linhas=tabela.total_linhas,
                amostra=tabela.amostra,
                metadados_amostra=tabela.metadados_amostra,
            )
            aviso = Aviso(
                mensagem=f"Sobrescrita de '{tabela.nome_tabela}' criada.",
                origem="SobrescritaDeTabela",
            )
            return Sucesso(curada, avisos=[aviso])

        tabelas = [fabrica_tabela_extraida("vendas", "pedidos")]
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.aplicar_sobrescritas(tabelas, _sobrescrita_com_aviso)

        assert isinstance(resultado, Sucesso)
        assert [aviso.mensagem for aviso in resultado.avisos] == [
            "Sobrescrita de 'pedidos' criada."
        ]

    def test_extrair_fk_composta_com_chave_candidata_nao_emite_aviso(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """FK composta que aponta para a PK composta real não emite Aviso."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.INTEGER)
        pedidos = _tabela_com_colunas(
            "vendas",
            "pedidos",
            colunas=[
                ColunaExtraida(nome="pais_id", tipo_dado=tipo),
                ColunaExtraida(nome="estado_id", tipo_dado=tipo),
            ],
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="vendas",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        estados = _tabela_com_colunas(
            "vendas",
            "estados",
            colunas=[
                ColunaExtraida(nome="pais_id", tipo_dado=tipo, chave_primaria=True),
                ColunaExtraida(nome="id", tipo_dado=tipo, chave_primaria=True),
            ],
        )
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "estados")])},
            tabelas_customizadas={
                ("vendas", "pedidos"): pedidos,
                ("vendas", "estados"): estados,
            },
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas"], extrator)

        assert isinstance(resultado, Sucesso)
        assert resultado.avisos == []


class TestErro:
    """Erro esperado."""

    def test_max_trabalhadores_zero_levanta_value_error(
        self,
    ) -> None:
        """max_trabalhadores=0 quebraria o ThreadPoolExecutor — rejeitado."""
        with pytest.raises(ValueError, match="max_trabalhadores"):
            OrquestradorParalelo(max_trabalhadores=0)

    def test_extrair_com_tabela_com_falha_devolve_sucesso_parcial(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Uma tabela falha entre várias — sucesso parcial com Aviso."""
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")])},
            {("vendas", "clientes"): "conexão perdida"},
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas"], extrator)

        assert isinstance(resultado, Sucesso)
        identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor]
        assert identificadores == [("vendas", "pedidos")]
        assert resultado.avisos == [
            Aviso(
                mensagem="Falha ao extrair 'vendas.clientes': conexão perdida",
                origem="OrquestradorParalelo",
            )
        ]

    def test_extrair_com_excecao_nao_prevista_acumula_como_aviso(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Exception não prevista dentro do worker vira Aviso isolado.

        Reproduz o boundary sistemático da issue #56 — sem executar_com_seguranca
        em volta da chamada no worker, isso propagaria crua via futuro.result(),
        quebrando a extração inteira em vez de virar um Aviso isolado, com as
        demais tabelas seguindo extraídas normalmente.
        """
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")])},
            excecoes_de_extracao={
                ("vendas", "clientes"): ValueError("dtype não suportado")
            },
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas"], extrator)

        assert isinstance(resultado, Sucesso)
        identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor]
        assert identificadores == [("vendas", "pedidos")]
        assert len(resultado.avisos) == 1
        mensagem = resultado.avisos[0].mensagem
        assert "vendas.clientes" in mensagem
        assert "ValueError" in mensagem
        assert "dtype não suportado" in mensagem

    def test_extrair_com_falha_de_listagem_de_escopo_acumula_como_aviso(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Escopo com erro de listagem acumula, não aborta os demais."""
        extrator = construir_extrator_fake(
            {
                "vendas": Sucesso([("vendas", "pedidos")]),
                "financeiro_typo": Falha("Escopo 'financeiro_typo' não encontrado."),
            }
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas", "financeiro_typo"], extrator)

        assert isinstance(resultado, Sucesso)
        identificadores = [(t.nome_escopo, t.nome_tabela) for t in resultado.valor]
        assert identificadores == [("vendas", "pedidos")]
        assert resultado.avisos == [
            Aviso(
                mensagem=(
                    "Falha ao listar tabelas de 'financeiro_typo': "
                    "Escopo 'financeiro_typo' não encontrado."
                ),
                origem="OrquestradorParalelo",
            )
        ]

    def test_aplicar_sobrescritas_com_falha_devolve_sucesso_parcial(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        construir_sobrescrita_fake: Callable[..., SobrescritaFake],
    ) -> None:
        """Uma sobrescrita falha entre várias — sucesso parcial."""
        tabelas = [
            fabrica_tabela_extraida("vendas", "pedidos"),
            fabrica_tabela_extraida("vendas", "clientes"),
        ]
        sobrescrita = construir_sobrescrita_fake(
            {("vendas", "clientes"): "YAML malformado"}
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.aplicar_sobrescritas(tabelas, sobrescrita)

        assert isinstance(resultado, Sucesso)
        identificadores = [
            (t.nome_escopo, t.nome_tabela) for t in resultado.valor.tabelas
        ]
        assert identificadores == [("vendas", "pedidos")]
        assert resultado.avisos == [
            Aviso(
                mensagem=(
                    "Falha ao aplicar sobrescrita em 'vendas.clientes': YAML malformado"
                ),
                origem="OrquestradorParalelo",
            )
        ]


class TestBorda:
    """Bordas."""

    def test_extrair_lista_de_escopos_vazia_retorna_sucesso_vazio(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Lista de escopos vazia retorna Sucesso com lista vazia."""
        extrator = construir_extrator_fake({})
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado: Resultado[list[TabelaExtraida]] = orquestrador.extrair([], extrator)

        assert resultado == Sucesso([])

    def test_aplicar_sobrescritas_lista_vazia_retorna_banco_curado_vazio(
        self,
        construir_sobrescrita_fake: Callable[..., SobrescritaFake],
    ) -> None:
        """Lista de tabelas vazia retorna Sucesso com BancoCurado vazio."""
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.aplicar_sobrescritas([], construir_sobrescrita_fake())

        assert isinstance(resultado, Sucesso)
        assert resultado.valor == BancoCurado(tabelas=[])

    def test_extrair_chama_progresso_uma_vez_por_tabela_concluida(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Progresso é chamado uma vez por tabela, sucesso ou falha."""
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")])},
            {("vendas", "clientes"): "conexão perdida"},
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)
        chamadas: list[str] = []

        orquestrador.extrair(["vendas"], extrator, progresso=chamadas.append)

        assert sorted(chamadas) == ["vendas.clientes", "vendas.pedidos"]

    def test_extrair_chama_ao_conhecer_total_com_o_total_real_a_extrair(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """ao_conhecer_total recebe o nº de pares após a listagem interna.

        Escopo com falha de listagem não entra na contagem — só os pares que
        de fato serão extraídos (issue #75, elimina listagem duplicada na CLI).
        """
        extrator = construir_extrator_fake(
            {
                "vendas": Sucesso([("vendas", "pedidos"), ("vendas", "clientes")]),
                "financeiro_typo": Falha("Escopo 'financeiro_typo' não encontrado."),
            }
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)
        totais: list[int] = []

        orquestrador.extrair(
            ["vendas", "financeiro_typo"], extrator, ao_conhecer_total=totais.append
        )

        assert totais == [2]

    def test_aplicar_sobrescritas_chama_progresso_uma_vez_por_tabela_concluida(
        self,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        construir_sobrescrita_fake: Callable[..., SobrescritaFake],
    ) -> None:
        """Progresso é chamado uma vez por tabela em aplicar_sobrescritas."""
        tabelas = [
            fabrica_tabela_extraida("vendas", "pedidos"),
            fabrica_tabela_extraida("vendas", "clientes"),
        ]
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)
        chamadas: list[str] = []

        orquestrador.aplicar_sobrescritas(
            tabelas, construir_sobrescrita_fake(), progresso=chamadas.append
        )

        assert sorted(chamadas) == ["vendas.clientes", "vendas.pedidos"]

    def test_extrair_fk_composta_sem_chave_candidata_emite_aviso(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """FK composta sem PK/UNIQUE do lado referenciado emite Aviso.

        Checagem cross-table (issue #95): "estados" está no lote, mas
        (pais_id, id) não é nem a PK nem um UNIQUE composto dela — sinal de
        banco legado malformado, não deve ser consumido em silêncio.
        """
        tipo = TipoDeDado(categoria=CategoriaDeDado.INTEGER)
        pedidos = _tabela_com_colunas(
            "vendas",
            "pedidos",
            colunas=[
                ColunaExtraida(nome="pais_id", tipo_dado=tipo),
                ColunaExtraida(nome="estado_id", tipo_dado=tipo),
            ],
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="vendas",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        estados = _tabela_com_colunas(
            "vendas",
            "estados",
            colunas=[
                ColunaExtraida(nome="id", tipo_dado=tipo, chave_primaria=True),
                ColunaExtraida(nome="pais_id", tipo_dado=tipo),
            ],
        )
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos"), ("vendas", "estados")])},
            tabelas_customizadas={
                ("vendas", "pedidos"): pedidos,
                ("vendas", "estados"): estados,
            },
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas"], extrator)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert resultado.avisos[0].origem == "OrquestradorParalelo"
        assert "vendas.pedidos" in resultado.avisos[0].mensagem
        assert "vendas.estados" in resultado.avisos[0].mensagem

    def test_extrair_fk_composta_fora_do_lote_emite_aviso_informativo(
        self,
        construir_extrator_fake: Callable[..., ExtratorFake],
    ) -> None:
        """Tabela referenciada fora do lote emite Aviso de "não verificado".

        Decisão da banca de revisão pós-implementação da #95: um `continue`
        silencioso aqui seria indistinguível de "checado e ok" — o Aviso deixa
        explícito que a integridade referencial não pôde ser verificada, sem
        afirmar que ela está malformada (mensagem/teor diferentes do caso
        "sem chave candidata", que já foi de fato checado e reprovado).
        """
        tipo = TipoDeDado(categoria=CategoriaDeDado.INTEGER)
        pedidos = _tabela_com_colunas(
            "vendas",
            "pedidos",
            colunas=[
                ColunaExtraida(nome="pais_id", tipo_dado=tipo),
                ColunaExtraida(nome="estado_id", tipo_dado=tipo),
            ],
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="geografia",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        extrator = construir_extrator_fake(
            {"vendas": Sucesso([("vendas", "pedidos")])},
            tabelas_customizadas={("vendas", "pedidos"): pedidos},
        )
        orquestrador = OrquestradorParalelo(max_trabalhadores=4)

        resultado = orquestrador.extrair(["vendas"], extrator)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert resultado.avisos[0].origem == "OrquestradorParalelo"
        assert "vendas.pedidos" in resultado.avisos[0].mensagem
        assert "geografia.estados" in resultado.avisos[0].mensagem
        assert "não verificada" in resultado.avisos[0].mensagem

"""Testes de ExtratorPostgres."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from psycopg2 import OperationalError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)


class TestFeliz:
    """Caminho feliz."""

    def test_extrator_postgres_satisfaz_extrator(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """ExtratorPostgres conforma ao Port Extrator."""
        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)

        assert isinstance(extrator, Extrator)

    def test_construcao_nao_cria_pool_imediatamente(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """__init__ não abre conexão — pool é preguiçoso."""
        ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)

        pool_classe_fake.assert_not_called()

    def test_primeiro_uso_cria_pool_com_parametros_corretos(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Pool criado com minconn=1, maxconn e dsn corretos no 1º uso."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, max_conexoes=5
        )
        extrator.listar_tabelas("public")

        pool_classe_fake.assert_called_once_with(
            minconn=1, maxconn=5, dsn="postgresql://fake", connect_timeout=50
        )

    def test_max_conexoes_padrao_dimensiona_pool_com_oito(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Sem max_conexoes explícito, pool e semáforo usam o default 8."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        extrator.listar_tabelas("public")

        pool_classe_fake.assert_called_once_with(
            minconn=1, maxconn=8, dsn="postgresql://fake", connect_timeout=50
        )

    def test_pool_e_reutilizado_entre_chamadas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Chamadas seguintes reaproveitam o pool já criado."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        extrator.listar_tabelas("public")
        extrator.listar_tabelas("public")

        pool_classe_fake.assert_called_once()

    def test_listar_escopos_retorna_escopos_ordenados(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """listar_escopos devolve os schemas retornados pelo cursor."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = [("public",), ("vendas",)]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_escopos()

        assert resultado == Sucesso(["public", "vendas"])
        pool_classe_fake.return_value.putconn.assert_called_once_with(conexao_fake)

    def test_listar_tabelas_retorna_tabelas_ordenadas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """listar_tabelas devolve as linhas retornadas pelo cursor."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = [
            ("public", "clientes"),
            ("public", "pedidos"),
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_tabelas("public")

        assert resultado == Sucesso([("public", "clientes"), ("public", "pedidos")])
        pool_classe_fake.return_value.putconn.assert_called_once_with(conexao_fake)

    def test_extrair_tabela_retorna_estrutura_completa(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """extrair_tabela monta colunas, PK, FK, total_linhas e amostra."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("pedidos", "id", "int4", None, None, None, "NO"),
                ("pedidos", "nome", "varchar", 100, None, None, "YES"),
                ("pedidos", "cliente_id", "int4", None, None, None, "NO"),
            ],  # colunas (schema inteiro)
            [("pedidos", "id")],  # PK (schema inteiro)
            [
                (
                    "pedidos",
                    "cliente_id",
                    "vendas",
                    "clientes",
                    "id",
                    "fk_pedidos_cliente",
                )
            ],  # FK, schema cross-referenciado (schema inteiro)
            [("pedidos", 5001, "nome")],  # UNIQUE, single-column (schema inteiro)
            [("pedidos", 1000.0)],  # total_linhas (schema inteiro)
            [("pedidos", 200)],  # largura_media (schema inteiro)
            [(1, "ana", 10), (2, "bia", 20)],  # amostra (só desta tabela)
        ]
        cursor_fake.description = [
            SimpleNamespace(name="id"),
            SimpleNamespace(name="nome"),
            SimpleNamespace(name="cliente_id"),
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "pedidos")

        assert isinstance(resultado, Sucesso)
        tabela = resultado.valor
        assert tabela.nome_tabela == "pedidos"
        assert tabela.nome_escopo == "public"
        assert tabela.total_linhas == 1000
        assert [coluna.nome for coluna in tabela.colunas] == [
            "id",
            "nome",
            "cliente_id",
        ]
        assert tabela.colunas[0].chave_primaria is True
        assert tabela.colunas[0].nao_nulavel is True
        assert tabela.colunas[1].tipo_dado.categoria == CategoriaDeDado.VARCHAR
        assert tabela.colunas[1].tipo_dado.tamanho_maximo == 100
        assert tabela.colunas[1].nao_nulavel is False
        assert tabela.colunas[1].unica is True
        assert tabela.colunas[2].chave_estrangeira is True
        assert tabela.colunas[2].unica is False
        assert tabela.colunas[2].referencias == [
            ReferenciaDeColuna(
                nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
            )
        ]
        assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"
        assert tabela.metadados_amostra.tamanho_amostra == 2
        # 2 conexões: 1 pra popular o cache de metadados do schema, 1 pra amostra.
        assert pool_classe_fake.return_value.putconn.call_count == 2
        pool_classe_fake.return_value.putconn.assert_called_with(conexao_fake)

    def test_segunda_extracao_no_mesmo_schema_reaproveita_cache_de_metadados(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """2ª extrair_tabela no mesmo schema não repete queries de metadado.

        Prova o ganho real da consolidação: a 1ª chamada popula o
        cache do schema inteiro; a 2ª tabela só busca a própria amostra — nada
        de colunas/PK/FK/UNIQUE/total_linhas é lido do banco de novo.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("pedidos", "id", "int4", None, None, None, "NO"),
                ("clientes", "id", "int4", None, None, None, "NO"),
            ],  # colunas — as 2 tabelas do schema, lidas de uma vez
            [("pedidos", "id"), ("clientes", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("pedidos", 10.0), ("clientes", 5.0)],  # total_linhas
            [("pedidos", 200), ("clientes", 200)],  # largura_media (schema inteiro)
            [],  # amostra de "pedidos"
            [],  # amostra de "clientes"
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        primeira = extrator.extrair_tabela("public", "pedidos")
        segunda = extrator.extrair_tabela("public", "clientes")

        assert isinstance(primeira, Sucesso)
        assert isinstance(segunda, Sucesso)
        assert primeira.valor.total_linhas == 10
        assert segunda.valor.total_linhas == 5
        # 6 queries de metadado (rodadas 1x só) + 1 amostra por tabela = 8.
        assert cursor_fake.fetchall.call_count == 8
        # 1 conexão pro cache de metadado (só na 1ª chamada) + 1 amostra por
        # tabela (2) = 3 — não 4, que seria o caso sem o cache reaproveitado.
        assert pool_classe_fake.return_value.putconn.call_count == 3

    def test_tabela_acima_do_limiar_de_linhas_usa_cursor_nomeado_em_lotes(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """total_linhas > limiar ativa streaming: cursor nomeado, itersize, commit."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("grande", "id", "int4", None, None, None, "NO")],  # colunas
            [("grande", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("grande", 200_000.0)],  # total_linhas — acima de 100_000
            [("grande", 200)],  # largura_media
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        cursor_fake.fetchmany.side_effect = [[(1,), (2,)], []]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "grande")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.tamanho_amostra == 2
        conexao_fake.cursor.assert_called_with(name="amostra_public_grande")
        assert cursor_fake.itersize == 50_000  # calcular_tamanho_lote(200)
        conexao_fake.commit.assert_called_once()
        # 6 queries de metadado (fetchall) + amostra via fetchmany, não fetchall.
        assert cursor_fake.fetchall.call_count == 6


class TestErro:
    """Erro esperado."""

    def test_max_conexoes_zero_levanta_value_error(
        self,
        configuracao: ConfiguracaoDeExtracao,
    ) -> None:
        """max_conexoes=0 travaria o semáforo pra sempre — rejeitado cedo."""
        with pytest.raises(ValueError, match="max_conexoes"):
            ExtratorPostgres(
                dsn="postgresql://fake", configuracao=configuracao, max_conexoes=0
            )

    def test_extrair_tabela_sem_estrategia_configurada_retorna_falha(
        self,
        pool_classe_fake: MagicMock,
    ) -> None:
        """extrair_tabela sem estratégia configurada vira Falha.

        Reproduz o cenário real do wizard reordenado (issue #75): o Extrator é
        construído por `conectar()` antes de `configurar_amostragem()` atribuir
        a estratégia — se algo chamar extrair_tabela nesse meio-tempo, precisa
        de uma Falha explícita, não um AttributeError sobre None.
        """
        configuracao_sem_estrategia = ConfiguracaoDeExtracao()
        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao_sem_estrategia
        )

        resultado = extrator.extrair_tabela("public", "clientes")

        assert isinstance(resultado, Falha)
        assert "sem estratégia" in resultado.erro
        pool_classe_fake.assert_not_called()

    def test_listar_escopos_com_conexao_recusada_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Falha ao obter conexão do pool vira Falha."""
        pool_classe_fake.return_value.getconn.side_effect = OperationalError(
            "connection refused"
        )

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_escopos()

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro

    def test_listar_tabelas_com_dsn_invalido_retorna_falha_sem_lancar_excecao(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """DSN inválido faz a própria criação do pool falhar.

        ThreadedConnectionPool conecta minconn conexões já no __init__ — sem o
        pool preguiçoso, essa OperationalError escaparia de listar_tabelas como
        exceção crua em vez de virar Falha.
        """
        pool_classe_fake.side_effect = OperationalError("connection refused")

        extrator = ExtratorPostgres(
            dsn="postgresql://invalido", configuracao=configuracao
        )
        resultado = extrator.listar_tabelas("public")

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro

    def test_listar_tabelas_com_conexao_recusada_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Falha ao obter conexão do pool (já criado) vira Falha."""
        pool_classe_fake.return_value.getconn.side_effect = OperationalError(
            "connection refused"
        )

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_tabelas("public")

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro

    def test_extrair_tabela_inexistente_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """schema/tabela sem colunas em information_schema vira Falha."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "inexistente")

        assert isinstance(resultado, Falha)
        assert "não encontrada" in resultado.erro
        pool_classe_fake.return_value.putconn.assert_called_once_with(conexao_fake)

    def test_extrair_tabela_com_conexao_recusada_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Falha ao obter conexão do pool vira Falha legível."""
        pool_classe_fake.return_value.getconn.side_effect = OperationalError(
            "connection refused"
        )

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "pedidos")

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro


class TestBorda:
    """Bordas."""

    def test_tabela_exatamente_no_limiar_de_linhas_nao_ativa_streaming(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """total_linhas == limiar (não >) segue com fetchall direto."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 100_000.0)],  # total_linhas — exatamente no limiar
            [("tabela", 200)],  # largura_media
            [(1,)],  # amostra
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "tabela")

        assert isinstance(resultado, Sucesso)
        conexao_fake.cursor.assert_called_with()
        cursor_fake.fetchmany.assert_not_called()
        conexao_fake.commit.assert_not_called()

    def test_connect_timeout_customizado_e_repassado_ao_pool(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """connect_timeout customizado é repassado ao ThreadedConnectionPool.

        Sem isso, um host inacessível por firewall (pacote descartado, não
        recusado) travaria por um timeout de TCP do SO — pode passar de um
        minuto — antes de qualquer mensagem de erro chegar à CLI.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, connect_timeout=3
        )
        extrator.listar_tabelas("public")

        pool_classe_fake.assert_called_once_with(
            minconn=1, maxconn=8, dsn="postgresql://fake", connect_timeout=3
        )

    def test_extrair_tabela_com_duas_fks_na_mesma_coluna_mantem_as_duas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Coluna com 2 FKs distintas (polimórfica) mantém as duas, sem Aviso."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("movimentos", "entidade_id", "int4", None, None, None, "YES")],  # colunas
            [],  # PK
            [
                (
                    "movimentos",
                    "entidade_id",
                    "vendas",
                    "clientes",
                    "id",
                    "fk_movimentos_clientes",
                ),
                (
                    "movimentos",
                    "entidade_id",
                    "vendas",
                    "fornecedores",
                    "id",
                    "fk_movimentos_fornecedores",
                ),
            ],  # FK duplicada na mesma coluna (2 constraints distintas)
            [],  # UNIQUE
            [("movimentos", 0.0)],  # total_linhas
            [("movimentos", 200)],  # largura_media (schema inteiro)
            [],  # amostra
        ]
        cursor_fake.description = [SimpleNamespace(name="entidade_id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "movimentos")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].referencias == [
            ReferenciaDeColuna(
                nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
            ),
            ReferenciaDeColuna(
                nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
            ),
        ]
        # Único Aviso remanescente é o de varredura completa da
        # AmostragemProbabilistica (fixture `configuracao`) — nenhum Aviso
        # de FK descartada, diferente do comportamento anterior à #105.
        assert len(resultado.avisos) == 1
        assert "varredura sequencial completa" in resultado.avisos[0].mensagem

    def test_extrair_tabela_com_unique_composto_monta_restricao_unica(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """UNIQUE(a, b) vira uma RestricaoUnica, sem marcar a/b como `unica`.

        Mesma tabela também tem uma coluna com UNIQUE single-column (índice
        diferente, indexrelid distinto) — prova que o agrupamento por
        (nome_tabela, indexrelid) não mistura os dois índices.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("enderecos", "codigo_pais", "varchar", 2, None, None, "NO"),
                ("enderecos", "codigo_local", "varchar", 10, None, None, "NO"),
                ("enderecos", "apelido", "varchar", 50, None, None, "YES"),
            ],  # colunas
            [],  # PK
            [],  # FK
            [
                ("enderecos", 5001, "codigo_pais"),
                ("enderecos", 5001, "codigo_local"),
                ("enderecos", 5002, "apelido"),
            ],  # UNIQUE — índice composto (5001) + índice single-column (5002)
            [("enderecos", 0.0)],  # total_linhas
            [("enderecos", 200)],  # largura_media (schema inteiro)
            [],  # amostra
        ]
        cursor_fake.description = [
            SimpleNamespace(name="codigo_pais"),
            SimpleNamespace(name="codigo_local"),
            SimpleNamespace(name="apelido"),
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "enderecos")

        assert isinstance(resultado, Sucesso)
        tabela = resultado.valor
        assert tabela.restricoes_unicas == [
            RestricaoUnica(colunas=("codigo_pais", "codigo_local"))
        ]
        assert tabela.colunas[0].unica is False
        assert tabela.colunas[1].unica is False
        assert tabela.colunas[2].unica is True

    def test_extrair_tabela_com_fk_composta_monta_restricao_de_fk_composta(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """FK(a, b) vira uma RestricaoDeFkComposta, sem afetar `.referencias`.

        Mesma tabela também tem uma FK single-column (constraint diferente) —
        prova que o agrupamento por constraint_name não mistura os dois casos,
        e que `ColunaExtraida.referencias` continua populado por coluna mesmo
        para as que fazem parte da constraint composta.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("pedidos", "pais_id", "int4", None, None, None, "NO"),
                ("pedidos", "estado_id", "int4", None, None, None, "NO"),
                ("pedidos", "cliente_id", "int4", None, None, None, "NO"),
            ],  # colunas
            [],  # PK
            [
                ("pedidos", "pais_id", "geografia", "estados", "pais_id", "fk_estado"),
                ("pedidos", "estado_id", "geografia", "estados", "id", "fk_estado"),
                ("pedidos", "cliente_id", "vendas", "clientes", "id", "fk_cliente"),
            ],  # FK — constraint composta (fk_estado) + single-column (fk_cliente)
            [],  # UNIQUE
            [("pedidos", 0.0)],  # total_linhas
            [("pedidos", 200)],  # largura_media (schema inteiro)
            [],  # amostra
        ]
        cursor_fake.description = [
            SimpleNamespace(name="pais_id"),
            SimpleNamespace(name="estado_id"),
            SimpleNamespace(name="cliente_id"),
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "pedidos")

        assert isinstance(resultado, Sucesso)
        tabela = resultado.valor
        assert tabela.restricoes_fk_compostas == [
            RestricaoDeFkComposta(
                colunas_locais=("pais_id", "estado_id"),
                nome_escopo_referenciado="geografia",
                nome_tabela_referenciada="estados",
                colunas_referenciadas=("pais_id", "id"),
            )
        ]
        assert tabela.colunas[0].referencias == [
            ReferenciaDeColuna(
                nome_escopo="geografia", nome_tabela="estados", nome_coluna="pais_id"
            )
        ]
        assert tabela.colunas[1].referencias == [
            ReferenciaDeColuna(
                nome_escopo="geografia", nome_tabela="estados", nome_coluna="id"
            )
        ]
        assert tabela.colunas[2].referencias == [
            ReferenciaDeColuna(
                nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
            )
        ]

    def test_listar_escopos_sem_escopos_de_usuario_retorna_lista_vazia(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """só schemas de sistema (já filtrados na query) retorna lista vazia."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_escopos()

        assert resultado == Sucesso([])

    def test_primeiro_uso_concorrente_cria_pool_uma_unica_vez(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Chamadas concorrentes no 1º uso criam o pool uma única vez.

        Sem lock em _obter_pool, duas threads poderiam ver self._pool is None ao
        mesmo tempo e construir o pool duas vezes — exatamente o cenário que o
        lock existe para prevenir.
        """
        primeira_thread_entrou = threading.Event()
        pode_prosseguir = threading.Event()

        def construir_pool_lento(**_kwargs: object) -> MagicMock:
            if not primeira_thread_entrou.is_set():
                primeira_thread_entrou.set()
                pode_prosseguir.wait(timeout=1)
            return MagicMock()

        pool_classe_fake.side_effect = construir_pool_lento

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, max_conexoes=10
        )

        thread_lenta = threading.Thread(target=extrator._obter_pool)
        thread_lenta.start()
        assert primeira_thread_entrou.wait(timeout=1) is True

        resultado_concorrente = extrator._obter_pool()
        pode_prosseguir.set()
        thread_lenta.join(timeout=1)

        assert pool_classe_fake.call_count == 1
        assert isinstance(resultado_concorrente, Sucesso)

    def test_metadados_de_schema_concorrentes_populam_cache_uma_unica_vez(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """2 chamadas concorrentes ao mesmo schema populam o cache 1x.

        Sem lock em _obter_metadados_schema, duas threads poderiam ver o cache
        do schema vazio ao mesmo tempo e rodar as 6 queries de metadado duas
        vezes cada — o ganho da consolidação (issue #66) dependeria de sorte de
        timing, não de garantia. Mesmo padrão de
        test_primeiro_uso_concorrente_cria_pool_uma_unica_vez, aplicado ao cache
        de schema em vez de ao pool de conexões.
        """
        primeira_thread_entrou = threading.Event()
        pode_prosseguir = threading.Event()
        respostas = iter(
            [
                [("pedidos", "id", "int4", None, None, None, "NO")],  # colunas
                [("pedidos", "id")],  # PK
                [],  # FK
                [],  # UNIQUE
                [("pedidos", 10.0)],  # total_linhas
                [("pedidos", 200)],  # largura_media (schema inteiro)
            ]
        )

        def fetchall_lento_na_primeira_chamada() -> list[tuple[object, ...]]:
            if not primeira_thread_entrou.is_set():
                primeira_thread_entrou.set()
                pode_prosseguir.wait(timeout=1)
            return next(respostas)

        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = fetchall_lento_na_primeira_chamada
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, max_conexoes=10
        )

        thread_lenta = threading.Thread(
            target=lambda: extrator._obter_metadados_schema("public")
        )
        thread_lenta.start()
        assert primeira_thread_entrou.wait(timeout=1) is True

        resultado_concorrente = extrator._obter_metadados_schema("public")
        pode_prosseguir.set()
        thread_lenta.join(timeout=1)

        assert cursor_fake.fetchall.call_count == 6
        assert isinstance(resultado_concorrente, Sucesso)
        assert extrator._cache_schemas["public"] is resultado_concorrente.valor

    def test_listar_tabelas_sem_tabelas_retorna_lista_vazia(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Schema sem tabelas retorna Sucesso com lista vazia."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.listar_tabelas("public")

        assert resultado == Sucesso([])

    def test_extrair_tabela_com_reltuples_negativo_usa_total_linhas_zero(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """reltuples=-1 (nunca analisada) vira total_linhas=0, não negativo."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela_nova", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela_nova", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela_nova", -1.0)],  # total_linhas
            [("tabela_nova", 200)],  # largura_media (schema inteiro)
            [],  # amostra
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "tabela_nova")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 0
        assert resultado.valor.metadados_amostra.tamanho_amostra == 0

    def test_tabela_ausente_de_pg_stats_usa_largura_media_padrao(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Tabela nunca analisada não aparece em pg_stats — cai no fallback."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 10.0)],  # total_linhas
            [],  # largura_media — sem linha nenhuma pra "tabela"
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator._obter_metadados_schema("public")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.largura_media_por_tabela == {}

    def test_tabela_com_estatistica_real_usa_soma_de_avg_width(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Largura média vem da soma de avg_width de todas as colunas da tabela."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 10.0)],  # total_linhas
            [("tabela", 57)],  # largura_media — soma real de avg_width
        ]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator._obter_metadados_schema("public")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.largura_media_por_tabela == {"tabela": 57}

    def test_amostra_maior_que_total_linhas_emite_aviso(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """tamanho_amostra > total_linhas emite Aviso (total_linhas desatualizado).

        reltuples reflete a última ANALYZE/autovacuum — pode ficar defasado
        logo após uma carga de dados (issue #56).
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("tabela_recem_carregada", "id", "int4", None, None, None, "NO")
            ],  # colunas
            [("tabela_recem_carregada", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela_recem_carregada", 1.0)],  # total_linhas desatualizado
            [("tabela_recem_carregada", 200)],  # largura_media (schema inteiro)
            [(1,), (2,)],  # amostra — 2 linhas
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "tabela_recem_carregada")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 1
        assert resultado.valor.metadados_amostra.tamanho_amostra == 2
        assert len(resultado.avisos) == 2
        assert resultado.avisos[1].origem == "ExtratorPostgres"
        assert "maior que total_linhas" in resultado.avisos[1].mensagem

    def test_amostragem_integral_usa_tamanho_da_amostra_como_total_linhas(
        self, pool_classe_fake: MagicMock, configuracao_integral: ConfiguracaoDeExtracao
    ) -> None:
        """Em AmostragemIntegral, total_linhas vira len(amostra), não catálogo.

        A estimativa de catálogo (3, propositalmente diferente do tamanho real
        da amostra) nunca aparece no resultado nem gera Aviso — em tabela inteira a
        tabela inteira já foi lida, então a divergência é estruturalmente
        impossível.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 3.0)],  # total_linhas de catálogo, desatualizado de propósito
            [("tabela", 200)],  # largura_media (schema inteiro)
            [(1,), (2,), (3,), (4,), (5,)],  # amostra — 5 linhas, a tabela inteira
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao_integral
        )
        resultado = extrator.extrair_tabela("public", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 5
        assert resultado.valor.metadados_amostra.tamanho_amostra == 5
        assert resultado.valor.metadados_amostra.percentual is None
        assert resultado.valor.metadados_amostra.seed is None
        assert resultado.avisos == []
        consulta_amostra = cursor_fake.execute.call_args_list[-1].args[0]
        assert "TABLESAMPLE" not in str(consulta_amostra)

    def test_percentual_de_linhas_sem_seed_gera_e_registra_um_seed(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Sem seed do usuário, o Extrator gera um e registra em MetadadosDeAmostra.

        Reprodutibilidade não é opt-in silencioso — mesmo sem seed explícito, a
        amostra usa REPEATABLE com um seed concreto, nunca deixando o Postgres
        escolher em silêncio.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 100.0)],  # total_linhas
            [("tabela", 200)],  # largura_media (schema inteiro)
            [(1,)],  # amostra
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
        resultado = extrator.extrair_tabela("public", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.seed is not None
        assert isinstance(resultado.valor.metadados_amostra.seed, int)

    def test_amostragem_por_faixa_usa_tablesample_system_e_avisa_vies(
        self,
        pool_classe_fake: MagicMock,
        configuracao_por_faixa: ConfiguracaoDeExtracao,
    ) -> None:
        """RequisicaoPorFaixa gera TABLESAMPLE SYSTEM e emite Aviso de viés.

        Diferente de PercentualDeLinhas (BERNOULLI), o Aviso aqui não é sobre
        varredura sequencial completa — é sobre viés de cluster, incondicional
        toda vez que a estratégia é usada.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [("tabela", "id", "int4", None, None, None, "NO")],  # colunas
            [("tabela", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [("tabela", 100.0)],  # total_linhas
            [("tabela", 200)],  # largura_media (schema inteiro)
            [(1,)],  # amostra
        ]
        cursor_fake.description = [SimpleNamespace(name="id")]
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao_por_faixa
        )
        resultado = extrator.extrair_tabela("public", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.estrategia == "amostragem_por_faixa"
        assert resultado.valor.total_linhas == 100
        assert len(resultado.avisos) == 1
        assert "página física de disco" in resultado.avisos[0].mensagem
        consulta_amostra = cursor_fake.execute.call_args_list[-1].args[0]
        assert "TABLESAMPLE SYSTEM" in str(consulta_amostra)

    def test_max_conexoes_um_faz_segunda_chamada_concorrente_esperar(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """max_conexoes=1 serializa chamadas concorrentes em vez de exaurir o pool.

        ThreadedConnectionPool.getconn() levantaria PoolError se duas chamadas
        pedissem conexão ao mesmo tempo com maxconn=1 — o semáforo interno faz a
        2ª chamada esperar a 1ª liberar a conexão, em vez de deixar o erro escapar.
        """
        primeira_em_andamento = threading.Event()
        pode_liberar_primeira = threading.Event()

        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value

        def fetchall_bloqueante() -> list[tuple[str, str]]:
            primeira_em_andamento.set()
            pode_liberar_primeira.wait(timeout=1)
            return []

        cursor_fake.fetchall.side_effect = fetchall_bloqueante
        pool_classe_fake.return_value.getconn.return_value = conexao_fake

        extrator = ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, max_conexoes=1
        )

        thread_primeira = threading.Thread(
            target=lambda: extrator.listar_tabelas("public")
        )
        thread_primeira.start()
        assert primeira_em_andamento.wait(timeout=1) is True

        semaforo_livre_durante_a_primeira = extrator._semaforo.acquire(timeout=0.2)
        assert semaforo_livre_durante_a_primeira is False

        pode_liberar_primeira.set()
        thread_primeira.join(timeout=1)

        semaforo_livre_apos_a_primeira = extrator._semaforo.acquire(timeout=1)
        assert semaforo_livre_apos_a_primeira is True
        extrator._semaforo.release()

"""Testes de ExtratorMariaDB."""

import threading
from unittest.mock import MagicMock

import pymysql
import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.mariadb._queries import (
    LARGURA_MEDIA_PADRAO_BYTES,
)
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)

from .conftest import montar_metadados_side_effect


class TestFeliz:
    """Caminho feliz."""

    def test_extrator_mariadb_satisfaz_extrator(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """ExtratorMariaDB conforma ao Port Extrator (Open/Closed)."""
        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )

        assert isinstance(extrator, Extrator)

    def test_construcao_nao_cria_pool_imediatamente(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """__init__ não abre conexão — pool é preguiçoso."""
        ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )

        pool_classe_fake.assert_not_called()

    def test_primeiro_uso_cria_pool_com_parametros_corretos(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Pool criado com os parâmetros de conexão corretos no 1º uso."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao,
            port=3307,
            max_conexoes=5,
        )
        extrator.listar_tabelas("vendas")

        pool_classe_fake.assert_called_once_with(
            creator=pymysql,
            mincached=1,
            maxcached=5,
            maxconnections=5,
            blocking=True,
            host="fake",
            port=3307,
            user="root",
            password="senha",
            autocommit=True,
            connect_timeout=10,
        )

    def test_pool_e_reutilizado_entre_chamadas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Chamadas seguintes reaproveitam o pool já criado."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        extrator.listar_tabelas("vendas")
        extrator.listar_tabelas("vendas")

        pool_classe_fake.assert_called_once()

    def test_listar_escopos_retorna_escopos_ordenados(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """listar_escopos devolve os databases retornados pelo cursor."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = [("vendas",), ("rh",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_escopos()

        assert resultado == Sucesso(["vendas", "rh"])
        conexao_fake.close.assert_called_once()

    def test_listar_tabelas_retorna_tabelas_ordenadas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """listar_tabelas devolve as linhas retornadas pelo cursor."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = [
            ("vendas", "clientes"),
            ("vendas", "pedidos"),
        ]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_tabelas("vendas")

        assert resultado == Sucesso([("vendas", "clientes"), ("vendas", "pedidos")])
        conexao_fake.close.assert_called_once()

    def test_extrair_tabela_retorna_estrutura_completa(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """colunas, PK, FK, total_linhas, amostra e promoção de BOOLEAN."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="pedidos",
                colunas=[
                    ("id", "int", "int(11)", None, None, None, "NO"),
                    ("nome", "varchar", "varchar(100)", 100, None, None, "YES"),
                    ("ativo", "tinyint", "tinyint(1)", None, None, None, "NO"),
                    ("cliente_id", "int", "int(11)", None, None, None, "NO"),
                ],
                pks=["id"],
                fks=[("cliente_id", "vendas", "clientes", "id", "fk_pedidos_cliente")],
                unicas=[("nome", "nome")],
                total_linhas=1000,
            ),
            [(1, "ana", 1, 10), (2, "bia", 0, 20)],  # amostra
        ]
        cursor_fake.description = [("id",), ("nome",), ("ativo",), ("cliente_id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "pedidos")

        assert isinstance(resultado, Sucesso)
        tabela = resultado.valor
        assert tabela.nome_tabela == "pedidos"
        assert tabela.nome_escopo == "vendas"
        assert tabela.total_linhas == 1000
        assert [coluna.nome for coluna in tabela.colunas] == [
            "id",
            "nome",
            "ativo",
            "cliente_id",
        ]
        assert tabela.colunas[0].chave_primaria is True
        assert tabela.colunas[0].nao_nulavel is True
        assert tabela.colunas[1].tipo_dado.categoria == CategoriaDeDado.VARCHAR
        assert tabela.colunas[1].tipo_dado.tamanho_maximo == 100
        assert tabela.colunas[1].nao_nulavel is False
        assert tabela.colunas[1].unica is True
        assert tabela.colunas[2].tipo_dado.categoria == CategoriaDeDado.BOOLEAN
        assert tabela.colunas[3].chave_estrangeira is True
        assert tabela.colunas[3].unica is False
        assert tabela.colunas[3].referencias == [
            ReferenciaDeColuna(
                nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
            )
        ]
        assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"
        assert tabela.metadados_amostra.tamanho_amostra == 2
        # 2 conexões: 1 pra popular o cache de metadados do escopo, 1 pra amostra.
        assert conexao_fake.close.call_count == 2

    def test_tabela_acima_do_limiar_de_linhas_usa_sscursor_em_lotes(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """total_linhas > limiar ativa streaming: SSCursor lido via fetchmany."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="grande",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=200_000,  # acima de 100_000
            ),
        ]
        cursor_fake.description = [("id",)]
        cursor_fake.fetchmany.side_effect = [[(1,), (2,)], []]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "grande")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.tamanho_amostra == 2
        conexao_fake.cursor.assert_called_with(pymysql.cursors.SSCursor)
        # 6 queries de metadado (fetchall) + amostra via fetchmany, não fetchall.
        assert cursor_fake.fetchall.call_count == 6

    def test_segunda_extracao_no_mesmo_schema_reaproveita_cache_de_metadados(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """2ª extrair_tabela no mesmo escopo não repete queries de metadado.

        Prova o ganho real da consolidação (issue #104): a 1ª chamada popula
        o cache do escopo inteiro; a 2ª tabela só busca a própria amostra —
        nada de colunas/PK/FK/UNIQUE/JSON/total_linhas é lido do banco de novo.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("pedidos", "id", "int", "int(11)", None, None, None, "NO"),
                ("clientes", "id", "int", "int(11)", None, None, None, "NO"),
            ],  # colunas — as 2 tabelas do escopo, lidas de uma vez
            [("pedidos", "id"), ("clientes", "id")],  # PK
            [],  # FK
            [],  # UNIQUE
            [],  # JSON
            [("pedidos", 10, 200), ("clientes", 5, 200)],  # total_linhas
            [],  # amostra de "pedidos"
            [],  # amostra de "clientes"
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        primeira = extrator.extrair_tabela("vendas", "pedidos")
        segunda = extrator.extrair_tabela("vendas", "clientes")

        assert isinstance(primeira, Sucesso)
        assert isinstance(segunda, Sucesso)
        assert primeira.valor.total_linhas == 10
        assert segunda.valor.total_linhas == 5
        # 6 queries de metadado (rodadas 1x só) + 1 amostra por tabela = 8.
        assert cursor_fake.fetchall.call_count == 8
        # 1 conexão pro cache de metadado (só na 1ª chamada) + 1 amostra por
        # tabela (2) = 3 — não 4, que seria o caso sem o cache reaproveitado.
        assert conexao_fake.close.call_count == 3

    def test_coluna_json_e_reclassificada_via_check_clause(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Coluna LONGTEXT com CHECK json_valid vira categoria JSON.

        MariaDB nunca reporta data_type == "json" (issue #56) — a coluna real
        reportada é "longtext"; a reclassificação depende só do CHECK_CLAUSE.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="pedidos",
                colunas=[
                    ("id", "int", "int(11)", None, None, None, "NO"),
                    ("dados", "longtext", "longtext", None, None, None, "YES"),
                ],
                pks=["id"],
                check_clauses=["json_valid(`dados`)"],
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("id",), ("dados",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "pedidos")

        assert isinstance(resultado, Sucesso)
        coluna_dados = next(c for c in resultado.valor.colunas if c.nome == "dados")
        assert coluna_dados.tipo_dado.categoria == CategoriaDeDado.JSON

    def test_tinyint_um_unsigned_tambem_e_candidato_a_boolean(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """tinyint(1) unsigned com amostra só 0/1 também é promovido."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="flags",
                colunas=[
                    (
                        "ativo",
                        "tinyint",
                        "tinyint(1) unsigned",
                        None,
                        None,
                        None,
                        "YES",
                    ),
                ],
            ),
            [(1,), (0,), (1,)],  # amostra
        ]
        cursor_fake.description = [("ativo",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "flags")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.BOOLEAN

    def test_unique_com_nome_identico_em_duas_tabelas_nao_colide(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """UNIQUE(email) de nomes idênticos em 2 tabelas não se misturam.

        Regressão direcionada: nomes de constraint no MariaDB são escopados
        por tabela, não pelo escopo inteiro (bug corrigido uma vez na issue
        #44). A consolidação por escopo (#104) precisa continuar separando
        por `(table_name, constraint_name)`, não só `constraint_name` —
        `clientes.email` e `fornecedores.email` usam o mesmo nome de
        constraint ("email"), mas são UNIQUEs independentes.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                ("clientes", "email", "varchar", "varchar(255)", 255, None, None, "NO"),
                (
                    "fornecedores",
                    "email",
                    "varchar",
                    "varchar(255)",
                    255,
                    None,
                    None,
                    "NO",
                ),
            ],  # colunas
            [],  # PK
            [],  # FK
            [
                ("clientes", "email", "email"),
                ("fornecedores", "email", "email"),
            ],  # UNIQUE — mesmo constraint_name ("email"), tabelas diferentes
            [],  # JSON
            [("clientes", 0, 200), ("fornecedores", 0, 200)],  # total_linhas
            [],  # amostra de "clientes"
            [],  # amostra de "fornecedores"
        ]
        cursor_fake.description = [("email",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        clientes = extrator.extrair_tabela("vendas", "clientes")
        fornecedores = extrator.extrair_tabela("vendas", "fornecedores")

        assert isinstance(clientes, Sucesso)
        assert isinstance(fornecedores, Sucesso)
        assert clientes.valor.colunas[0].unica is True
        assert fornecedores.valor.colunas[0].unica is True

    def test_check_com_nome_identico_em_duas_tabelas_nao_colide(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """CHECK de nome idêntico em 2 tabelas não vaza classificação JSON.

        Regressão direcionada, prova a correção de um bug pré-existente
        (issue #104): `information_schema.check_constraints` não filtra por
        tabela em `_COLUNAS_JSON_SQL` — a atribuição correta depende do
        `table_name` nativo dessa view. "produtos.chk_json" (CHECK JSON de
        verdade) e "pedidos.chk_json" (CHECK não relacionado a JSON, mesmo
        nome de constraint) não podem se misturar.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            [
                (
                    "produtos",
                    "atributos",
                    "longtext",
                    "longtext",
                    None,
                    None,
                    None,
                    "YES",
                ),
                ("pedidos", "quantidade", "int", "int(11)", None, None, None, "NO"),
            ],  # colunas
            [],  # PK
            [],  # FK
            [],  # UNIQUE
            [
                ("produtos", "json_valid(`atributos`)"),
                ("pedidos", "`quantidade` >= 0"),
            ],  # JSON — mesmo constraint_name ("chk_json") em tabelas diferentes
            [("produtos", 0, 200), ("pedidos", 0, 200)],  # total_linhas
            [],  # amostra de "produtos"
            [],  # amostra de "pedidos"
        ]
        cursor_fake.description = [("atributos",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        produtos = extrator.extrair_tabela("vendas", "produtos")
        pedidos = extrator.extrair_tabela("vendas", "pedidos")

        assert isinstance(produtos, Sucesso)
        assert isinstance(pedidos, Sucesso)
        assert produtos.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.JSON
        assert pedidos.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.INTEGER


class TestErro:
    """Erro esperado."""

    def test_excecao_durante_streaming_fecha_cursor_e_conexao_antes_de_propagar(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Erro no meio do fetchmany fecha o SSCursor antes de propagar.

        Sem isso, um SSCursor não drenado ficaria pra ser fechado só pelo
        GC (via `__del__`), gerando o AttributeError silenciosamente
        engolido apontado pelo engenheiro de dados.
        """
        conexao_fake = MagicMock()
        cursor_context = conexao_fake.cursor.return_value
        cursor_context.__exit__.return_value = False  # não suprime a exceção
        cursor_fake = cursor_context.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="grande",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=200_000,  # acima do limiar
            ),
        ]
        cursor_fake.description = [("id",)]
        cursor_fake.fetchmany.side_effect = pymysql.err.OperationalError(
            "conexão perdida"
        )
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )

        with pytest.raises(pymysql.err.OperationalError):
            extrator.extrair_tabela("vendas", "grande")

        # 1ª chamada (metadados) sai normal; 2ª (amostra streaming) carrega
        # a exceção — prova que o __exit__ do SSCursor rodou antes dela
        # propagar, não só o da 1ª conexão (metadados).
        ultima_saida = cursor_context.__exit__.call_args_list[-1]
        assert ultima_saida.args[0] is pymysql.err.OperationalError
        # 2 conexões (metadados + amostra) — a 2ª fecha mesmo com exceção.
        assert conexao_fake.close.call_count == 2

    def test_max_conexoes_zero_levanta_value_error(
        self,
        configuracao: ConfiguracaoDeExtracao,
    ) -> None:
        """max_conexoes=0 é rejeitado cedo, antes de qualquer conexão."""
        with pytest.raises(ValueError, match="max_conexoes"):
            ExtratorMariaDB(
                host="fake",
                user="root",
                password="senha",
                configuracao=configuracao,
                max_conexoes=0,
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
        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao_sem_estrategia,
        )

        resultado = extrator.extrair_tabela("public", "clientes")

        assert isinstance(resultado, Falha)
        assert "sem estratégia" in resultado.erro
        pool_classe_fake.assert_not_called()

    def test_listar_escopos_com_pool_indisponivel_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Falha ao criar o pool (host inválido) vira Falha."""
        pool_classe_fake.side_effect = pymysql.err.OperationalError(
            "connection refused"
        )

        extrator = ExtratorMariaDB(
            host="invalido", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_escopos()

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro

    def test_listar_tabelas_com_conexao_recusada_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Falha ao obter conexão do pool (já criado) vira Falha."""
        pool_classe_fake.return_value.connection.side_effect = (
            pymysql.err.OperationalError("connection refused")
        )

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_tabelas("vendas")

        assert isinstance(resultado, Falha)
        assert "Não foi possível conectar" in resultado.erro

    def test_extrair_tabela_inexistente_retorna_falha(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """escopo/tabela sem colunas em information_schema vira Falha."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "inexistente")

        assert isinstance(resultado, Falha)
        assert "não encontrada" in resultado.erro
        conexao_fake.close.assert_called_once()


class TestBorda:
    """Bordas."""

    def test_tabela_exatamente_no_limiar_de_linhas_nao_ativa_streaming(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """total_linhas == limiar (não >) segue com fetchall direto."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=100_000,  # exatamente no limiar
            ),
            [(1,)],  # amostra
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "tabela")

        assert isinstance(resultado, Sucesso)
        conexao_fake.cursor.assert_called_with()
        cursor_fake.fetchmany.assert_not_called()

    def test_connect_timeout_customizado_e_repassado_ao_pool(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """connect_timeout customizado é repassado ao PooledDB."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao,
            connect_timeout=3,
        )
        extrator.listar_tabelas("vendas")

        pool_classe_fake.assert_called_once_with(
            creator=pymysql,
            mincached=1,
            maxcached=8,
            maxconnections=8,
            blocking=True,
            host="fake",
            port=3306,
            user="root",
            password="senha",
            autocommit=True,
            connect_timeout=3,
        )

    def test_extrair_tabela_com_duas_fks_na_mesma_coluna_mantem_as_duas(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Coluna com 2 FKs distintas (polimórfica) mantém as duas, sem Aviso."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="movimentos",
                colunas=[
                    ("entidade_id", "int", "int(11)", None, None, None, "YES"),
                ],
                fks=[
                    (
                        "entidade_id",
                        "vendas",
                        "clientes",
                        "id",
                        "fk_movimentos_clientes",
                    ),
                    (
                        "entidade_id",
                        "vendas",
                        "fornecedores",
                        "id",
                        "fk_movimentos_fornecedores",
                    ),
                ],  # FK duplicada na mesma coluna (2 constraints distintas)
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("entidade_id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "movimentos")

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

    def test_listar_escopos_sem_databases_de_usuario_retorna_lista_vazia(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """só databases de sistema (já filtrados na query) retorna lista vazia."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_escopos()

        assert resultado == Sucesso([])

    def test_extrair_tabela_com_table_rows_nulo_usa_total_linhas_zero(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """TABLE_ROWS NULL (engine sem estatística) vira total_linhas=0."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela_nova",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=None,
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "tabela_nova")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 0
        assert resultado.valor.metadados_amostra.tamanho_amostra == 0

    def test_avg_row_length_nulo_usa_largura_media_padrao(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """AVG_ROW_LENGTH NULL (tabela nunca analisada) cai no fallback."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela_nova",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=10,
                largura_media=None,
            ),
            [],  # amostra
        ]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator._obter_metadados_schema("vendas")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.largura_media_por_tabela == {
            "tabela_nova": LARGURA_MEDIA_PADRAO_BYTES
        }

    def test_avg_row_length_real_e_usado_diretamente(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """AVG_ROW_LENGTH real do catálogo é usado sem transformação."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=10,
                largura_media=84,
            ),
            [],  # amostra
        ]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator._obter_metadados_schema("vendas")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.largura_media_por_tabela == {"tabela": 84}

    def test_amostra_maior_que_total_linhas_emite_aviso(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """tamanho_amostra > total_linhas emite Aviso (total_linhas desatualizado).

        TABLE_ROWS é estimativa do MariaDB — pode ficar defasada logo após uma
        carga de dados (issue #56).
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela_recem_carregada",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=1,  # desatualizado
            ),
            [(1,), (2,)],  # amostra — 2 linhas
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "tabela_recem_carregada")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 1
        assert resultado.valor.metadados_amostra.tamanho_amostra == 2
        assert len(resultado.avisos) == 2
        assert resultado.avisos[1].origem == "ExtratorMariaDB"
        assert "maior que total_linhas" in resultado.avisos[1].mensagem

    def test_amostragem_integral_usa_tamanho_da_amostra_como_total_linhas(
        self, pool_classe_fake: MagicMock, configuracao_integral: ConfiguracaoDeExtracao
    ) -> None:
        """Em AmostragemIntegral, total_linhas vira len(amostra), não TABLE_ROWS.

        A estimativa de catálogo (3, propositalmente diferente do tamanho real
        da amostra) nunca aparece no resultado nem gera Aviso — em tabela inteira a
        tabela inteira já foi lida, então a divergência é estruturalmente
        impossível.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=3,  # de catálogo, desatualizado
            ),
            [(1,), (2,), (3,), (4,), (5,)],  # amostra — 5 linhas, a tabela inteira
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao_integral,
        )
        resultado = extrator.extrair_tabela("vendas", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.total_linhas == 5
        assert resultado.valor.metadados_amostra.tamanho_amostra == 5
        assert resultado.valor.metadados_amostra.percentual is None
        assert resultado.valor.metadados_amostra.seed is None
        assert resultado.avisos == []
        consulta_amostra = cursor_fake.execute.call_args_list[-1].args[0]
        assert "RAND" not in consulta_amostra

    def test_percentual_de_linhas_sem_seed_gera_e_registra_um_seed(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Sem seed do usuário, o Extrator gera um e registra em MetadadosDeAmostra.

        Reprodutibilidade não é opt-in silencioso — mesmo sem seed explícito, a
        amostra usa RAND(seed) com um valor concreto, nunca deixando o MariaDB
        escolher em silêncio.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "int", "int(11)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=100,
            ),
            [(1,)],  # amostra
        ]
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.seed is not None
        assert isinstance(resultado.valor.metadados_amostra.seed, int)

    def test_amostragem_por_faixa_com_pk_elegivel_usa_uniao_de_faixas(
        self,
        pool_classe_fake: MagicMock,
        configuracao_por_faixa: ConfiguracaoDeExtracao,
    ) -> None:
        """PK bigint de coluna única: consulta vira UNIÃO de faixas com corte fixo.

        O corte de cada faixa é sorteado em Python (não `RAND()` no SQL —
        reavaliado por linha pelo motor, colapsaria a amostra pro início do
        intervalo de PK) e embutido como parâmetro literal. Aviso de viés
        cita o mecanismo real (faixas contíguas de chave primária), distinto
        do texto do ExtratorPostgres (página física).
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "bigint", "bigint(20)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=20,  # n_pedido pequeno (2), 3 linhas não é "gap denso"
            ),
            [(1,), (2,), (3,)],  # amostra
        ]
        cursor_fake.fetchone.return_value = (999,)
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao_por_faixa,
        )
        resultado = extrator.extrair_tabela("vendas", "tabela")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.metadados_amostra.estrategia == "amostragem_por_faixa"
        assert len(resultado.avisos) == 1
        assert "faixas contíguas de chave primária" in resultado.avisos[0].mensagem
        chamada_amostra = cursor_fake.execute.call_args_list[-1]
        consulta_amostra, parametros_amostra = chamada_amostra.args
        assert consulta_amostra.count("UNION ALL") == 9  # 10 faixas, 9 uniões
        assert "RAND" not in consulta_amostra  # corte é sorteado em Python, não SQL
        # 2 parâmetros por faixa (cutoff, limit) x 10 faixas
        assert len(parametros_amostra) == 20
        cortes = parametros_amostra[0::2]
        assert all(0 <= corte <= 999 for corte in cortes)  # MAX(id) mockado = 999
        assert len(set(cortes)) > 1  # seeds distintas por faixa -> cortes distintos

    def test_amostragem_por_faixa_sem_pk_cai_no_fallback_probabilistico(
        self,
        pool_classe_fake: MagicMock,
        configuracao_por_faixa: ConfiguracaoDeExtracao,
    ) -> None:
        """Tabela sem PK: cai para WHERE RAND(seed) <= p, com Aviso de fallback.

        O fallback reusa exatamente o mecanismo de PercentualDeLinhas — soma
        os dois Avisos: o de fallback (explica o motivo) e o de varredura
        sequencial completa (automático, mesmo caminho de AmostragemProbabilistica).
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela_sem_pk",
                colunas=[("valor", "int", "int(11)", None, None, None, "NO")],
                total_linhas=1_000,
            ),
            [(1,), (2,)],  # amostra
        ]
        cursor_fake.description = [("valor",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao_por_faixa,
        )
        resultado = extrator.extrair_tabela("vendas", "tabela_sem_pk")

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 2
        assert "caiu para o mecanismo probabilístico padrão" in (
            resultado.avisos[0].mensagem
        )
        assert "tabela sem chave primária" in resultado.avisos[0].mensagem
        assert "varredura sequencial completa" in resultado.avisos[1].mensagem
        consulta_amostra = cursor_fake.execute.call_args_list[-1].args[0]
        assert "RAND(%s) <= %s" in consulta_amostra

    def test_amostragem_por_faixa_com_poucos_resultados_avisa_gaps_densos(
        self,
        pool_classe_fake: MagicMock,
        configuracao_por_faixa: ConfiguracaoDeExtracao,
    ) -> None:
        """Amostra bem menor que o n pedido soma um Aviso de gaps densos na PK."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="tabela",
                colunas=[("id", "bigint", "bigint(20)", None, None, None, "NO")],
                pks=["id"],
                total_linhas=1_000,
            ),
            [(1,)],  # amostra — bem menos que os 100 linhas pedidas (10% de 1000)
        ]
        cursor_fake.fetchone.return_value = (999,)
        cursor_fake.description = [("id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao_por_faixa,
        )
        resultado = extrator.extrair_tabela("vendas", "tabela")

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 2
        assert "gaps densos" in resultado.avisos[0].mensagem

    def test_tinyint_um_com_valor_atipico_na_amostra_mantem_integer(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """tinyint(1) com valor fora de {0,1} na amostra não é promovido."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="contadores",
                colunas=[
                    ("contador", "tinyint", "tinyint(1)", None, None, None, "YES"),
                ],
            ),
            [(0,), (1,), (2,)],  # amostra com valor atípico
        ]
        cursor_fake.description = [("contador",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "contadores")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.INTEGER

    def test_tinyint_um_com_amostra_vazia_mantem_integer(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """tinyint(1) sem nenhum valor amostrado não é promovido (sem evidência)."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="flags",
                colunas=[
                    ("ativo", "tinyint", "tinyint(1)", None, None, None, "YES"),
                ],
            ),
            [],  # amostra vazia
        ]
        cursor_fake.description = [("ativo",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "flags")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.INTEGER

    def test_unique_composta_nao_marca_nenhuma_coluna_como_unica(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """UNIQUE(a, b) não torna 'a' nem 'b' únicas individualmente."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="enderecos",
                colunas=[
                    ("codigo_pais", "varchar", "varchar(2)", 2, None, None, "NO"),
                    ("codigo_local", "varchar", "varchar(10)", 10, None, None, "NO"),
                ],
                unicas=[
                    ("uk_pais_local", "codigo_pais"),
                    ("uk_pais_local", "codigo_local"),
                ],  # UNIQUE composta — mesmo constraint_name, 2 colunas
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("codigo_pais",), ("codigo_local",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "enderecos")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].unica is False
        assert resultado.valor.colunas[1].unica is False
        assert resultado.valor.restricoes_unicas == [
            RestricaoUnica(colunas=("codigo_pais", "codigo_local"))
        ]

    def test_fk_composta_monta_restricao_de_fk_composta(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """FK(a, b) vira uma RestricaoDeFkComposta, sem afetar `.referencias`.

        Mesma tabela também tem uma FK single-column (constraint diferente) —
        prova que o agrupamento por constraint_name não mistura os dois casos,
        e que `ColunaExtraida.referencias` continua populado por coluna mesmo
        para as que fazem parte da constraint composta. Sem query nova — só
        reagrupamento sobre a mesma `_CHAVES_ESTRANGEIRAS_SQL` (issue #95).
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="pedidos",
                colunas=[
                    ("pais_id", "int", "int(11)", None, None, None, "NO"),
                    ("estado_id", "int", "int(11)", None, None, None, "NO"),
                    ("cliente_id", "int", "int(11)", None, None, None, "NO"),
                ],
                fks=[
                    ("pais_id", "geografia", "estados", "pais_id", "fk_estado"),
                    ("estado_id", "geografia", "estados", "id", "fk_estado"),
                    ("cliente_id", "vendas", "clientes", "id", "fk_cliente"),
                ],  # FK — constraint composta (fk_estado) + single-column (fk_cliente)
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("pais_id",), ("estado_id",), ("cliente_id",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "pedidos")

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

    def test_check_clause_com_coluna_inexistente_nao_reclassifica(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """CHECK_CLAUSE cujo nome de coluna não existe na tabela é ignorado.

        Defesa em profundidade de `_colunas_json_de_check_clauses`: mesmo com
        o `table_name` nativo de `check_constraints` já resolvendo a
        atribuição correta por tabela, um CHECK_CLAUSE que não segue o padrão
        `json_valid(<coluna real>)` não deve reclassificar nada.
        """
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.side_effect = [
            *montar_metadados_side_effect(
                tabela="pedidos",
                colunas=[("nome", "varchar", "varchar(50)", 50, None, None, "YES")],
                check_clauses=["json_valid(`coluna_inexistente`)"],
            ),
            [],  # amostra
        ]
        cursor_fake.description = [("nome",)]
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.extrair_tabela("vendas", "pedidos")

        assert isinstance(resultado, Sucesso)
        assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.VARCHAR

    def test_listar_tabelas_sem_tabelas_retorna_lista_vazia(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """Escopo sem tabelas retorna Sucesso com lista vazia."""
        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
        cursor_fake.fetchall.return_value = []
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake", user="root", password="senha", configuracao=configuracao
        )
        resultado = extrator.listar_tabelas("vendas")

        assert resultado == Sucesso([])

    def test_metadados_de_schema_concorrentes_populam_cache_uma_unica_vez(
        self, pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """2 chamadas concorrentes ao mesmo escopo populam o cache 1x.

        Sem lock em `_obter_metadados_schema`, duas threads poderiam ver o
        cache do escopo vazio ao mesmo tempo e rodar as 6 queries de metadado
        duas vezes cada — o ganho da consolidação (issue #104) dependeria de
        sorte de timing, não de garantia. Mesmo padrão do teste equivalente do
        `ExtratorPostgres` (issue #66), aplicado ao pool `blocking=True` do
        MariaDB.
        """
        primeira_thread_entrou = threading.Event()
        pode_prosseguir = threading.Event()
        respostas = iter(
            [
                [
                    ("pedidos", "id", "int", "int(11)", None, None, None, "NO")
                ],  # colunas
                [("pedidos", "id")],  # PK
                [],  # FK
                [],  # UNIQUE
                [],  # JSON
                [("pedidos", 10, 200)],  # total_linhas
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
        pool_classe_fake.return_value.connection.return_value = conexao_fake

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao,
            max_conexoes=10,
        )

        thread_lenta = threading.Thread(
            target=lambda: extrator._obter_metadados_schema("vendas")
        )
        thread_lenta.start()
        assert primeira_thread_entrou.wait(timeout=1) is True

        resultado_concorrente = extrator._obter_metadados_schema("vendas")
        pode_prosseguir.set()
        thread_lenta.join(timeout=1)

        assert cursor_fake.fetchall.call_count == 6
        assert isinstance(resultado_concorrente, Sucesso)
        assert extrator._cache_schemas["vendas"] is resultado_concorrente.valor

    def test_max_conexoes_um_faz_segunda_chamada_concorrente_esperar(
        self, monkeypatch: pytest.MonkeyPatch, configuracao: ConfiguracaoDeExtracao
    ) -> None:
        """max_conexoes=1 serializa chamadas concorrentes em vez de falhar.

        Diferente do ExtratorPostgres (semáforo próprio), o ExtratorMariaDB não
        implementa nenhuma sincronização — depende inteiramente de
        `PooledDB(blocking=True)` bloquear internamente quando o pool está
        saturado. Por isso este teste não usa `pool_classe_fake` (que mocka
        `PooledDB` inteiro, escondendo justamente o comportamento sob teste) —
        só substitui `pymysql.connect`, o `creator` que o `PooledDB` real chama
        por baixo, mantendo a lógica de bloqueio real da biblioteca em jogo.
        """
        primeira_em_andamento = threading.Event()
        pode_liberar_primeira = threading.Event()

        conexao_fake = MagicMock()
        cursor_fake = conexao_fake.cursor.return_value

        def fetchall_bloqueante() -> list[tuple[str, str]]:
            primeira_em_andamento.set()
            pode_liberar_primeira.wait(timeout=1)
            return []

        cursor_fake.fetchall.side_effect = fetchall_bloqueante
        monkeypatch.setattr(pymysql, "connect", lambda *args, **kwargs: conexao_fake)

        extrator = ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao,
            max_conexoes=1,
        )

        thread_primeira = threading.Thread(
            target=lambda: extrator.listar_tabelas("public")
        )
        thread_primeira.start()
        assert primeira_em_andamento.wait(timeout=1) is True

        segunda_terminou = threading.Event()

        def alvo_segunda() -> None:
            extrator.listar_tabelas("public")
            segunda_terminou.set()

        thread_segunda = threading.Thread(target=alvo_segunda)
        thread_segunda.start()

        segunda_terminou_cedo = segunda_terminou.wait(timeout=0.2)
        assert segunda_terminou_cedo is False

        pode_liberar_primeira.set()
        thread_primeira.join(timeout=1)
        thread_segunda.join(timeout=1)
        assert segunda_terminou.is_set() is True

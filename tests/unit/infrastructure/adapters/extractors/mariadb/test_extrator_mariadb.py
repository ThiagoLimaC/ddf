"""Testes de ExtratorMariaDB."""

import threading
from unittest.mock import MagicMock

import pymysql
import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)

# Caminho feliz


def test_extrator_mariadb_satisfaz_extrator(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: ExtratorMariaDB conforma ao Port Extrator (Open/Closed)."""
    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )

    assert isinstance(extrator, Extrator)


def test_construcao_nao_cria_pool_imediatamente(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: __init__ não abre conexão — pool é preguiçoso."""
    ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )

    pool_classe_fake.assert_not_called()


def test_primeiro_uso_cria_pool_com_parametros_corretos(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: pool criado com os parâmetros de conexão corretos no 1º uso."""
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
    )


def test_pool_e_reutilizado_entre_chamadas(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: chamadas seguintes reaproveitam o pool já criado."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_escopos devolve os databases retornados pelo cursor."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_tabelas devolve as linhas retornadas pelo cursor."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: colunas, PK, FK, total_linhas, amostra e promoção de BOOLEAN."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [
            ("id", "int", "int(11)", None, None, None, "NO"),
            ("nome", "varchar", "varchar(100)", 100, None, None, "YES"),
            ("ativo", "tinyint", "tinyint(1)", None, None, None, "NO"),
            ("cliente_id", "int", "int(11)", None, None, None, "NO"),
        ],  # colunas
        [("id",)],  # PK
        [("cliente_id", "vendas", "clientes", "id")],  # FK
        [("nome", "nome")],  # UNIQUE (single-column)
        [],  # JSON
        [(1, "ana", 1, 10), (2, "bia", 0, 20)],  # amostra
    ]
    cursor_fake.fetchone.return_value = (1000,)
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
    assert tabela.colunas[3].referencia == ReferenciaDeColuna(
        nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
    )
    assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"
    assert tabela.metadados_amostra.tamanho_amostra == 2
    conexao_fake.close.assert_called_once()


def test_coluna_json_e_reclassificada_via_check_clause(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: coluna LONGTEXT com CHECK json_valid vira categoria JSON.

    MariaDB nunca reporta data_type == "json" (issue #56) — a coluna real
    reportada é "longtext"; a reclassificação depende só do CHECK_CLAUSE.
    """
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [
            ("id", "int", "int(11)", None, None, None, "NO"),
            ("dados", "longtext", "longtext", None, None, None, "YES"),
        ],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # UNIQUE
        [("json_valid(`dados`)",)],  # JSON
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (0,)
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: tinyint(1) unsigned com amostra só 0/1 também é promovido."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [
            ("ativo", "tinyint", "tinyint(1) unsigned", None, None, None, "YES"),
        ],  # colunas
        [],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [(1,), (0,), (1,)],  # amostra
    ]
    cursor_fake.fetchone.return_value = (3,)
    cursor_fake.description = [("ativo",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "flags")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.BOOLEAN


# Erro esperado


def test_max_conexoes_zero_levanta_value_error(
    configuracao: ConfiguracaoDeExtracao,
) -> None:
    """Erro esperado: max_conexoes=0 é rejeitado cedo, antes de qualquer conexão."""
    with pytest.raises(ValueError, match="max_conexoes"):
        ExtratorMariaDB(
            host="fake",
            user="root",
            password="senha",
            configuracao=configuracao,
            max_conexoes=0,
        )


def test_listar_escopos_com_pool_indisponivel_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: falha ao criar o pool (host inválido) vira Falha."""
    pool_classe_fake.side_effect = pymysql.err.OperationalError("connection refused")

    extrator = ExtratorMariaDB(
        host="invalido", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.listar_escopos()

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


def test_listar_tabelas_com_conexao_recusada_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: falha ao obter conexão do pool (já criado) vira Falha."""
    pool_classe_fake.return_value.connection.side_effect = pymysql.err.OperationalError(
        "connection refused"
    )

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.listar_tabelas("vendas")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


def test_extrair_tabela_inexistente_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: escopo/tabela sem colunas em information_schema vira Falha."""
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


# Borda


def test_extrair_tabela_com_duas_fks_na_mesma_coluna_emite_aviso(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: coluna com 2 FKs mantém só a última e emite Aviso não-fatal."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("entidade_id", "int", "int(11)", None, None, None, "YES")],  # colunas
        [],  # PK
        [
            ("entidade_id", "vendas", "clientes", "id"),
            ("entidade_id", "vendas", "fornecedores", "id"),
        ],  # FK duplicada na mesma coluna
        [],  # UNIQUE
        [],  # JSON
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (0,)
    cursor_fake.description = [("entidade_id",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "movimentos")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].referencia == ReferenciaDeColuna(
        nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
    )
    assert len(resultado.avisos) == 1
    assert resultado.avisos[0].origem == "ExtratorMariaDB"


def test_listar_escopos_sem_databases_de_usuario_retorna_lista_vazia(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: só databases de sistema (já filtrados na query) retorna lista vazia."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: TABLE_ROWS NULL (engine sem estatística) vira total_linhas=0."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("id", "int", "int(11)", None, None, None, "NO")],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (None,)
    cursor_fake.description = [("id",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "tabela_nova")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 0
    assert resultado.valor.metadados_amostra.tamanho_amostra == 0


def test_amostra_maior_que_total_linhas_emite_aviso(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: tamanho_amostra > total_linhas emite Aviso (total_linhas desatualizado).

    TABLE_ROWS é estimativa do MariaDB — pode ficar defasada logo após uma
    carga de dados (issue #56).
    """
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("id", "int", "int(11)", None, None, None, "NO")],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [(1,), (2,)],  # amostra — 2 linhas
    ]
    cursor_fake.fetchone.return_value = (1,)  # total_linhas desatualizado
    cursor_fake.description = [("id",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "tabela_recem_carregada")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 1
    assert resultado.valor.metadados_amostra.tamanho_amostra == 2
    assert len(resultado.avisos) == 1
    assert resultado.avisos[0].origem == "ExtratorMariaDB"
    assert "maior que total_linhas" in resultado.avisos[0].mensagem


def test_amostragem_integral_usa_tamanho_da_amostra_como_total_linhas(
    pool_classe_fake: MagicMock, configuracao_integral: ConfiguracaoDeExtracao
) -> None:
    """Borda: em AmostragemIntegral, total_linhas vira len(amostra), não TABLE_ROWS.

    A estimativa de catálogo (3, propositalmente diferente do tamanho real
    da amostra) nunca aparece no resultado nem gera Aviso — em tabela inteira a
    tabela inteira já foi lida, então a divergência é estruturalmente
    impossível.
    """
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("id", "int", "int(11)", None, None, None, "NO")],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [(1,), (2,), (3,), (4,), (5,)],  # amostra — 5 linhas, a tabela inteira
    ]
    cursor_fake.fetchone.return_value = (3,)  # total_linhas de catálogo, desatualizado
    cursor_fake.description = [("id",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao_integral
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: sem seed do usuário, o Extrator gera um e registra em MetadadosDeAmostra.

    Reprodutibilidade não é opt-in silencioso — mesmo sem seed explícito, a
    amostra usa RAND(seed) com um valor concreto, nunca deixando o MariaDB
    escolher em silêncio.
    """
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("id", "int", "int(11)", None, None, None, "NO")],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [(1,)],  # amostra
    ]
    cursor_fake.fetchone.return_value = (100,)  # total_linhas
    cursor_fake.description = [("id",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "tabela")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.metadados_amostra.seed is not None
    assert isinstance(resultado.valor.metadados_amostra.seed, int)


def test_tinyint_um_com_valor_atipico_na_amostra_mantem_integer(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: tinyint(1) com valor fora de {0,1} na amostra não é promovido."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("contador", "tinyint", "tinyint(1)", None, None, None, "YES")],  # colunas
        [],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [(0,), (1,), (2,)],  # amostra com valor atípico
    ]
    cursor_fake.fetchone.return_value = (3,)
    cursor_fake.description = [("contador",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "contadores")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.INTEGER


def test_tinyint_um_com_amostra_vazia_mantem_integer(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: tinyint(1) sem nenhum valor amostrado não é promovido (sem evidência)."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("ativo", "tinyint", "tinyint(1)", None, None, None, "YES")],  # colunas
        [],  # PK
        [],  # FK
        [],  # UNIQUE
        [],  # JSON
        [],  # amostra vazia
    ]
    cursor_fake.fetchone.return_value = (0,)
    cursor_fake.description = [("ativo",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "flags")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.INTEGER


def test_unique_composta_nao_marca_nenhuma_coluna_como_unica(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: UNIQUE(a, b) não torna 'a' nem 'b' únicas individualmente."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [
            ("codigo_pais", "varchar", "varchar(2)", 2, None, None, "NO"),
            ("codigo_local", "varchar", "varchar(10)", 10, None, None, "NO"),
        ],  # colunas
        [],  # PK
        [],  # FK
        [
            ("uk_pais_local", "codigo_pais"),
            ("uk_pais_local", "codigo_local"),
        ],  # UNIQUE composta — mesmo constraint_name, 2 colunas
        [],  # JSON
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (0,)
    cursor_fake.description = [("codigo_pais",), ("codigo_local",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "enderecos")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].unica is False
    assert resultado.valor.colunas[1].unica is False


def test_check_clause_de_outra_tabela_nao_reclassifica_coluna(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: CHECK_CLAUSE cujo nome de coluna não existe nesta tabela é ignorado.

    Reproduz o fan-out do JOIN documentado em _COLUNAS_JSON_SQL — nomes de
    constraint são escopados por tabela no MariaDB, e CHECK_CONSTRAINTS não
    tem TABLE_NAME pra filtrar isso na query. Aqui a tabela consultada só
    tem a coluna "nome" (VARCHAR); "outra_coluna" no CHECK_CLAUSE simula o
    resultado de uma constraint de mesmo nome vinda de outra tabela do
    schema — não deve reclassificar nada.
    """
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("nome", "varchar", "varchar(50)", 50, None, None, "YES")],  # colunas
        [],  # PK
        [],  # FK
        [],  # UNIQUE
        [("json_valid(`outra_coluna`)",)],  # JSON — de outra tabela
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (0,)
    cursor_fake.description = [("nome",)]
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.extrair_tabela("vendas", "pedidos")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.colunas[0].tipo_dado.categoria == CategoriaDeDado.VARCHAR


def test_listar_tabelas_sem_tabelas_retorna_lista_vazia(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: escopo sem tabelas retorna Sucesso com lista vazia."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.connection.return_value = conexao_fake

    extrator = ExtratorMariaDB(
        host="fake", user="root", password="senha", configuracao=configuracao
    )
    resultado = extrator.listar_tabelas("vendas")

    assert resultado == Sucesso([])


# Borda


def test_max_conexoes_um_faz_segunda_chamada_concorrente_esperar(
    monkeypatch: pytest.MonkeyPatch, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: max_conexoes=1 serializa chamadas concorrentes em vez de falhar.

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

    thread_primeira = threading.Thread(target=lambda: extrator.listar_tabelas("public"))
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

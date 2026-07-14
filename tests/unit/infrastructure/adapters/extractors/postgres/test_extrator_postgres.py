"""Testes de ExtratorPostgres."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from psycopg2 import OperationalError

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

# Caminho feliz


def test_extrator_postgres_satisfaz_extrator(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: ExtratorPostgres conforma ao Port Extrator."""
    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)

    assert isinstance(extrator, Extrator)


def test_construcao_nao_cria_pool_imediatamente(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: __init__ não abre conexão — pool é preguiçoso."""
    ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)

    pool_classe_fake.assert_not_called()


def test_primeiro_uso_cria_pool_com_parametros_corretos(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: pool criado com minconn=1, maxconn e dsn corretos no 1º uso."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(
        dsn="postgresql://fake", configuracao=configuracao, max_conexoes=5
    )
    extrator.listar_tabelas("public")

    pool_classe_fake.assert_called_once_with(
        minconn=1, maxconn=5, dsn="postgresql://fake"
    )


def test_max_conexoes_padrao_dimensiona_pool_com_oito(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: sem max_conexoes explícito, pool e semáforo usam o default 8."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    extrator.listar_tabelas("public")

    pool_classe_fake.assert_called_once_with(
        minconn=1, maxconn=8, dsn="postgresql://fake"
    )


def test_pool_e_reutilizado_entre_chamadas(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: chamadas seguintes reaproveitam o pool já criado."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    extrator.listar_tabelas("public")
    extrator.listar_tabelas("public")

    pool_classe_fake.assert_called_once()


def test_listar_escopos_retorna_escopos_ordenados(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_escopos devolve os schemas retornados pelo cursor."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = [("public",), ("vendas",)]
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.listar_escopos()

    assert resultado == Sucesso(["public", "vendas"])
    pool_classe_fake.return_value.putconn.assert_called_once_with(conexao_fake)


def test_listar_tabelas_retorna_tabelas_ordenadas(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_tabelas devolve as linhas retornadas pelo cursor."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: extrair_tabela monta colunas, PK, FK, total_linhas e amostra."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [
            ("id", "integer", None, None, None),
            ("nome", "character varying", 100, None, None),
            ("cliente_id", "integer", None, None, None),
        ],  # colunas
        [("id",)],  # PK
        [("cliente_id", "vendas", "clientes", "id")],  # FK (schema cross-referenciado)
        [(1, "ana", 10), (2, "bia", 20)],  # amostra
    ]
    cursor_fake.fetchone.return_value = (1000.0,)
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
    assert [coluna.nome for coluna in tabela.colunas] == ["id", "nome", "cliente_id"]
    assert tabela.colunas[0].chave_primaria is True
    assert tabela.colunas[1].tipo_dado.categoria == CategoriaDeDado.VARCHAR
    assert tabela.colunas[1].tipo_dado.tamanho_maximo == 100
    assert tabela.colunas[2].chave_estrangeira is True
    assert tabela.colunas[2].referencia == ReferenciaDeColuna(
        nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
    )
    assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"
    assert tabela.metadados_amostra.tamanho_amostra == 2
    pool_classe_fake.return_value.putconn.assert_called_once_with(conexao_fake)


# Erro esperado


def test_max_conexoes_zero_levanta_value_error(
    configuracao: ConfiguracaoDeExtracao,
) -> None:
    """Erro esperado: max_conexoes=0 travaria o semáforo pra sempre — rejeitado cedo."""
    with pytest.raises(ValueError, match="max_conexoes"):
        ExtratorPostgres(
            dsn="postgresql://fake", configuracao=configuracao, max_conexoes=0
        )


def test_listar_escopos_com_conexao_recusada_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: falha ao obter conexão do pool vira Falha."""
    pool_classe_fake.return_value.getconn.side_effect = OperationalError(
        "connection refused"
    )

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.listar_escopos()

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


def test_listar_tabelas_com_dsn_invalido_retorna_falha_sem_lancar_excecao(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: DSN inválido faz a própria criação do pool falhar.

    ThreadedConnectionPool conecta minconn conexões já no __init__ — sem o
    pool preguiçoso, essa OperationalError escaparia de listar_tabelas como
    exceção crua em vez de virar Falha.
    """
    pool_classe_fake.side_effect = OperationalError("connection refused")

    extrator = ExtratorPostgres(dsn="postgresql://invalido", configuracao=configuracao)
    resultado = extrator.listar_tabelas("public")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


def test_listar_tabelas_com_conexao_recusada_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: falha ao obter conexão do pool (já criado) vira Falha."""
    pool_classe_fake.return_value.getconn.side_effect = OperationalError(
        "connection refused"
    )

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.listar_tabelas("public")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


def test_extrair_tabela_inexistente_retorna_falha(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: schema/tabela sem colunas em information_schema vira Falha."""
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
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: falha ao obter conexão do pool vira Falha legível."""
    pool_classe_fake.return_value.getconn.side_effect = OperationalError(
        "connection refused"
    )

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.extrair_tabela("public", "pedidos")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


# Borda


def test_listar_escopos_sem_escopos_de_usuario_retorna_lista_vazia(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: só schemas de sistema (já filtrados na query) retorna lista vazia."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.listar_escopos()

    assert resultado == Sucesso([])


def test_primeiro_uso_concorrente_cria_pool_uma_unica_vez(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: chamadas concorrentes no 1º uso criam o pool uma única vez.

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


def test_listar_tabelas_sem_tabelas_retorna_lista_vazia(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: schema sem tabelas retorna Sucesso com lista vazia."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.return_value = []
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.listar_tabelas("public")

    assert resultado == Sucesso([])


def test_extrair_tabela_com_reltuples_negativo_usa_total_linhas_zero(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: reltuples=-1 (nunca analisada) vira total_linhas=0, não negativo."""
    conexao_fake = MagicMock()
    cursor_fake = conexao_fake.cursor.return_value.__enter__.return_value
    cursor_fake.fetchall.side_effect = [
        [("id", "integer", None, None, None)],  # colunas
        [("id",)],  # PK
        [],  # FK
        [],  # amostra
    ]
    cursor_fake.fetchone.return_value = (-1.0,)
    cursor_fake.description = [SimpleNamespace(name="id")]
    pool_classe_fake.return_value.getconn.return_value = conexao_fake

    extrator = ExtratorPostgres(dsn="postgresql://fake", configuracao=configuracao)
    resultado = extrator.extrair_tabela("public", "tabela_nova")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 0
    assert resultado.valor.metadados_amostra.tamanho_amostra == 0


def test_max_conexoes_um_faz_segunda_chamada_concorrente_esperar(
    pool_classe_fake: MagicMock, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: max_conexoes=1 serializa chamadas concorrentes em vez de exaurir o pool.

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

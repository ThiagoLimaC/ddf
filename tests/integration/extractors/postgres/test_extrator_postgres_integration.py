"""Testes de integração de ExtratorPostgres contra Postgres real (testcontainers)."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

# Caminho feliz


def test_listar_tabelas_retorna_tabelas_do_schema(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_tabelas retorna as tabelas semeadas, ordenadas."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.listar_tabelas("public")

    assert resultado == Sucesso([("public", "clientes"), ("public", "pedidos")])


def test_extrair_tabela_retorna_estrutura_completa(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: extrair_tabela lê colunas, PK, FK, total_linhas e amostra."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("public", "pedidos")

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    assert tabela.nome_tabela == "pedidos"
    assert tabela.nome_schema == "public"
    assert tabela.total_linhas == 3
    assert [coluna.nome for coluna in tabela.colunas] == ["id", "cliente_id", "valor"]

    coluna_id, coluna_fk, coluna_valor = tabela.colunas
    assert coluna_id.chave_primaria is True

    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.tabela_referenciada == "clientes"
    assert coluna_fk.coluna_referenciada == "id"

    assert coluna_valor.tipo_dado.categoria == CategoriaDeDado.NUMERIC
    assert coluna_valor.tipo_dado.precisao == 10
    assert coluna_valor.tipo_dado.escala == 2

    assert tabela.amostra.height == 3  # percentual=100 -> amostra completa
    assert tabela.metadados_amostra.tamanho_amostra == 3
    assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"


def test_extrair_tabela_mapeia_coluna_com_timezone(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: timestamp with time zone vira TIMESTAMP com_timezone=True."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("public", "clientes")

    assert isinstance(resultado, Sucesso)
    coluna_criado_em = resultado.valor.colunas[2]
    assert coluna_criado_em.nome == "criado_em"
    assert coluna_criado_em.tipo_dado.categoria == CategoriaDeDado.TIMESTAMP
    assert coluna_criado_em.tipo_dado.com_timezone is True


# Erro esperado


def test_extrair_tabela_inexistente_retorna_falha(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: tabela inexistente vira Falha, contra Postgres real."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("public", "tabela_fantasma")

    assert isinstance(resultado, Falha)
    assert "não encontrada" in resultado.erro


def test_extrair_tabela_com_dsn_invalido_retorna_falha(
    configuracao: ConfiguracaoDeExtracao,
) -> None:
    """Erro esperado: DSN apontando pra porta fechada vira Falha de conexão."""
    extrator = ExtratorPostgres(
        dsn="postgresql://user:pass@localhost:1/db", configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("public", "pedidos")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


# Borda


def test_listar_tabelas_schema_vazio_retorna_lista_vazia(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: schema real sem tabelas retorna Sucesso com lista vazia."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.listar_tabelas("vazio")

    assert resultado == Sucesso([])

"""Testes de integração de ExtratorMariaDB contra MariaDB real (testcontainers)."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)

# Caminho feliz


def test_listar_tabelas_retorna_tabelas_do_escopo(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_tabelas retorna as tabelas semeadas, ordenadas."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.listar_tabelas("vendas")

    assert resultado == Sucesso([("vendas", "clientes"), ("vendas", "pedidos")])


def test_extrair_tabela_retorna_estrutura_completa(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: extrair_tabela lê colunas, PK, FK, total_linhas e amostra."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("vendas", "pedidos")

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    assert tabela.nome_tabela == "pedidos"
    assert tabela.nome_escopo == "vendas"
    assert tabela.total_linhas == 3
    assert [coluna.nome for coluna in tabela.colunas] == ["id", "cliente_id", "valor"]

    coluna_id, coluna_fk, coluna_valor = tabela.colunas
    assert coluna_id.chave_primaria is True

    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.referencia == ReferenciaDeColuna(
        nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
    )

    assert coluna_valor.tipo_dado.categoria == CategoriaDeDado.NUMERIC
    assert coluna_valor.tipo_dado.precisao == 10
    assert coluna_valor.tipo_dado.escala == 2

    assert tabela.amostra.height == 3  # percentual=100 -> amostra completa
    assert tabela.metadados_amostra.tamanho_amostra == 3
    assert tabela.metadados_amostra.estrategia == "percentual_de_linhas"


def test_extrair_tabela_mapeia_coluna_datetime(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: DATETIME vira TIMESTAMP com com_timezone=False."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("vendas", "clientes")

    assert isinstance(resultado, Sucesso)
    coluna_criado_em = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "criado_em"
    )
    assert coluna_criado_em.tipo_dado.categoria == CategoriaDeDado.TIMESTAMP
    assert coluna_criado_em.tipo_dado.com_timezone is False


def test_extrair_tabela_mapeia_enum_com_valores_permitidos(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: ENUM vira CategoriaDeDado.ENUM com valores_permitidos."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("vendas", "clientes")

    assert isinstance(resultado, Sucesso)
    coluna_status = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "status"
    )
    assert coluna_status.tipo_dado.categoria == CategoriaDeDado.ENUM
    assert coluna_status.tipo_dado.valores_permitidos == ("ativo", "inativo")


def test_extrair_tabela_promove_tinyint_um_real_para_boolean(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: tinyint(1) com dados reais só 0/1 é promovido a BOOLEAN."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("vendas", "clientes")

    assert isinstance(resultado, Sucesso)
    coluna_ativo = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "ativo"
    )
    assert coluna_ativo.tipo_dado.categoria == CategoriaDeDado.BOOLEAN


def test_listar_escopos_retorna_escopos_semeados(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_escopos retorna os databases semeados, ordenados."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.listar_escopos()

    assert resultado == Sucesso(["pessoa", "rh", "vazio", "vendas"])


# Erro esperado


def test_extrair_tabela_inexistente_retorna_falha(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Erro esperado: tabela inexistente vira Falha, contra MariaDB real."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("vendas", "tabela_fantasma")

    assert isinstance(resultado, Falha)
    assert "não encontrada" in resultado.erro


def test_extrair_tabela_com_porta_invalida_retorna_falha(
    configuracao: ConfiguracaoDeExtracao,
) -> None:
    """Erro esperado: porta fechada vira Falha de conexão."""
    extrator = ExtratorMariaDB(
        host="localhost",
        port=1,
        user="root",
        password="test",
        configuracao=configuracao,
    )

    resultado = extrator.extrair_tabela("vendas", "pedidos")

    assert isinstance(resultado, Falha)
    assert "Não foi possível conectar" in resultado.erro


# Borda


def test_extrair_tabela_com_fk_cross_database_captura_escopo_de_destino(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: FK apontando pra tabela em outro database preserva o escopo de destino."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("rh", "funcionario")

    assert isinstance(resultado, Sucesso)
    coluna_fk = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "pessoa_id"
    )
    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.referencia == ReferenciaDeColuna(
        nome_escopo="pessoa", nome_tabela="pessoa", nome_coluna="id"
    )


def test_listar_tabelas_escopo_vazio_retorna_lista_vazia(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: database real sem tabelas retorna Sucesso com lista vazia."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.listar_tabelas("vazio")

    assert resultado == Sucesso([])

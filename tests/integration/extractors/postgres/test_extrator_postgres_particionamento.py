"""Testes de integração: tabela particionada (Postgres real, testcontainers)."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

# Caminho feliz


def test_listar_tabelas_exclui_particoes_mas_mantem_heranca_classica(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Partições-filhas (relkind='p' no pai) somem; herança clássica não."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.listar_tabelas("particionamento")

    assert resultado == Sucesso(
        [
            ("particionamento", "carro"),
            ("particionamento", "pedidos"),
            ("particionamento", "veiculo"),
        ]
    )


def test_extrair_tabela_particionada_agrega_total_linhas_das_particoes(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """total_linhas da mãe é a soma real das partições, não a estimativa (~0) dela."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("particionamento", "pedidos")

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    assert tabela.total_linhas == 50
    assert tabela.amostra.height == 50
    anos_amostrados = set(tabela.amostra["ano"].to_list())
    assert anos_amostrados == {2024, 2025}


# Borda


def test_extrair_tabela_de_heranca_classica_nao_e_tratada_como_particao(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Tabela de herança clássica (INHERITS) extrai normalmente, sem agregação."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("particionamento", "carro")

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    assert tabela.total_linhas == 1
    assert tabela.amostra.height == 1

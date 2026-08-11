"""Corretude do paralelismo intra-tabela (item 5 da #126) contra MariaDB 11 real.

Mocks não conseguem validar a parte de maior risco desta feature: um erro
de particionamento por faixa de PK (overlap ou gap entre faixas) corrompe a
amostra silenciosamente, sem levantar nenhuma exceção — precisa de um
MariaDB de verdade, mesmo racional do teste equivalente do
ExtratorPostgres.

Não roda por padrão em CI de PR pesado (usa `testcontainers`, como os
demais testes de integração já existentes), mas não é `benchmark` — mede
corretude, não performance, então continua rodando na suíte normal.
"""

from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

import ddf.infrastructure.adapters.extractors.comum.leitura_paralela_intra_tabela as paralelismo  # noqa: E501
from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira import (
    TabelaInteira,
)
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)

_N_LINHAS = 50_000

_DDL = f"""
    CREATE TABLE vendas.tabela_grande (
        id INT AUTO_INCREMENT PRIMARY KEY,
        valor VARCHAR(50) NOT NULL,
        categoria INT NOT NULL
    ) ENGINE=InnoDB;
    INSERT INTO vendas.tabela_grande (valor, categoria)
        SELECT CONCAT('v', seq), seq % 7 FROM vendas.seq_1_to_{_N_LINHAS};
    ANALYZE TABLE vendas.tabela_grande;
"""


@pytest.fixture(scope="module")
def conexao_tabela_grande() -> Iterator[tuple[str, int]]:
    """Sobe um MariaDB 11 descartável com uma tabela de 50k linhas."""
    with MySqlContainer(
        "mariadb:11", username="root", root_password="test", dbname="vendas"
    ) as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(container.port))
        conexao_raiz = pymysql.connect(
            host=host, port=port, user="root", password="test", autocommit=True
        )
        try:
            with conexao_raiz.cursor() as cursor:
                for comando in _DDL.strip().split(";"):
                    comando = comando.strip()
                    if comando:
                        cursor.execute(comando)
        finally:
            conexao_raiz.close()
        yield (host, port)


def test_leitura_paralela_produz_as_mesmas_linhas_que_a_sequencial(
    conexao_tabela_grande: tuple[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AmostragemIntegral paralela e sequencial devolvem o mesmo conjunto de linhas.

    Extrai a mesma tabela duas vezes: uma com o limiar de paralelismo no
    valor real (bem acima de 50k linhas, cai no caminho sequencial de
    sempre) e outra com o limiar derrubado pra 0 (força o caminho paralelo
    a ativar). Se o particionamento por faixa de PK estiver correto, os
    dois devem devolver exatamente o mesmo conjunto de `id`s — nenhuma
    linha duplicada (overlap entre faixas) nem perdida (gap entre faixas).
    """
    host, port = conexao_tabela_grande
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())

    extrator_sequencial = ExtratorMariaDB(
        host=host, port=port, user="root", password="test", configuracao=configuracao
    )
    resultado_sequencial = extrator_sequencial.extrair_tabela("vendas", "tabela_grande")
    assert isinstance(resultado_sequencial, Sucesso)

    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    extrator_paralelo = ExtratorMariaDB(
        host=host,
        port=port,
        user="root",
        password="test",
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )
    resultado_paralelo = extrator_paralelo.extrair_tabela("vendas", "tabela_grande")
    assert isinstance(resultado_paralelo, Sucesso)

    ids_sequencial = sorted(resultado_sequencial.valor.amostra["id"].to_list())
    ids_paralelo = sorted(resultado_paralelo.valor.amostra["id"].to_list())

    assert resultado_sequencial.valor.total_linhas == _N_LINHAS
    assert resultado_paralelo.valor.total_linhas == _N_LINHAS
    assert ids_paralelo == ids_sequencial
    assert len(ids_paralelo) == len(set(ids_paralelo))  # sem duplicata (overlap)


def test_leitura_paralela_ativa_de_verdade_e_emite_aviso_de_consistencia(
    conexao_tabela_grande: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Confirma que o teste de corretude acima não passou "por acidente".

    Prova que o caminho paralelo foi de fato exercitado (não que caiu no
    sequencial e coincidentemente bateu com ele mesmo), e que o Aviso de
    risco de consistência entre faixas (sem equivalente a SET TRANSACTION
    SNAPSHOT no MariaDB) é emitido.
    """
    host, port = conexao_tabela_grande
    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorMariaDB(
        host=host,
        port=port,
        user="root",
        password="test",
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )

    with caplog.at_level("INFO"):
        resultado = extrator.extrair_tabela("vendas", "tabela_grande")

    assert isinstance(resultado, Sucesso)
    assert "paralelismo intra-tabela ativado" in caplog.text
    assert any(
        "sem garantia de consistência entre faixas" in aviso.mensagem
        for aviso in resultado.avisos
    )

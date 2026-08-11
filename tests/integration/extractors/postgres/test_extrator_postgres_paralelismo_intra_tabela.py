"""Corretude do paralelismo intra-tabela (issue #126) contra Postgres 16 real.

Mocks não conseguem validar a parte de maior risco desta feature: `SET
TRANSACTION SNAPSHOT` entre conexões distintas e o particionamento físico
por `ctid` precisam de um Postgres de verdade — um erro de partição
(overlap ou gap entre faixas) corrompe a amostra silenciosamente, sem
levantar nenhuma exceção.

Não roda por padrão em CI de PR pesado (usa `testcontainers`, como os
demais testes de integração já existentes), mas não é `benchmark` — mede
corretude, não performance, então continua rodando na suíte normal.
"""

import threading
from collections.abc import Iterator

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

import ddf.infrastructure.adapters.extractors.comum.leitura_paralela_intra_tabela as paralelismo  # noqa: E501
import ddf.infrastructure.adapters.extractors.postgres.extrator_postgres as extrator_postgres_module  # noqa: E501
from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira import (
    TabelaInteira,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

_N_LINHAS = 50_000

_DDL = f"""
    CREATE TABLE public.tabela_grande (
        id INTEGER PRIMARY KEY,
        valor TEXT NOT NULL,
        categoria INTEGER NOT NULL
    );
    INSERT INTO public.tabela_grande (id, valor, categoria)
    SELECT g, 'v' || g, g % 7
    FROM generate_series(1, {_N_LINHAS}) AS g;
    ANALYZE public.tabela_grande;
"""


@pytest.fixture(scope="module")
def dsn_tabela_grande() -> Iterator[str]:
    """Sobe um Postgres 16 descartável com uma tabela de 50k linhas."""
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        with psycopg2.connect(url) as conexao:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute(_DDL)
        yield url


def test_leitura_paralela_produz_as_mesmas_linhas_que_a_sequencial(
    dsn_tabela_grande: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AmostragemIntegral paralela e sequencial devolvem o mesmo conjunto de linhas.

    Extrai a mesma tabela duas vezes: uma com o limiar de paralelismo no
    valor real (bem acima de 50k linhas, cai no caminho sequencial de
    sempre) e outra com o limiar derrubado pra 0 (força o caminho paralelo
    a ativar). Se o particionamento por `ctid`/snapshot estiver correto,
    os dois devem devolver exatamente o mesmo conjunto de `id`s — nenhuma
    linha duplicada (overlap entre faixas) nem perdida (gap entre faixas).
    """
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())

    extrator_sequencial = ExtratorPostgres(
        dsn=dsn_tabela_grande, configuracao=configuracao
    )
    resultado_sequencial = extrator_sequencial.extrair_tabela("public", "tabela_grande")
    assert isinstance(resultado_sequencial, Sucesso)

    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    extrator_paralelo = ExtratorPostgres(
        dsn=dsn_tabela_grande,
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )
    resultado_paralelo = extrator_paralelo.extrair_tabela("public", "tabela_grande")
    assert isinstance(resultado_paralelo, Sucesso)

    ids_sequencial = sorted(resultado_sequencial.valor.amostra["id"].to_list())
    ids_paralelo = sorted(resultado_paralelo.valor.amostra["id"].to_list())

    assert resultado_sequencial.valor.total_linhas == _N_LINHAS
    assert resultado_paralelo.valor.total_linhas == _N_LINHAS
    assert ids_paralelo == ids_sequencial
    assert len(ids_paralelo) == len(set(ids_paralelo))  # sem duplicata (overlap)


def test_leitura_paralela_ativa_de_verdade_quando_elegivel(
    dsn_tabela_grande: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Confirma que o teste de corretude acima não passou "por acidente".

    Prova que o caminho paralelo foi de fato exercitado (não que caiu no
    sequencial e coincidentemente bateu com ele mesmo) — sem isso, o teste
    de corretude acima poderia estar validando dois caminhos sequenciais
    idênticos, não um paralelo contra um sequencial.
    """
    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorPostgres(
        dsn=dsn_tabela_grande,
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )

    with caplog.at_level("INFO"):
        resultado = extrator.extrair_tabela("public", "tabela_grande")

    assert isinstance(resultado, Sucesso)
    assert "paralelismo intra-tabela ativado" in caplog.text


def test_falha_do_connectorx_cai_para_sequencial_em_vez_de_derrubar_a_tabela(
    dsn_tabela_grande: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Crash conhecido do connectorx (ex.: NUMERIC sem escala fixa) não derruba tudo.

    Antes desta correção, qualquer exceção de `cx.read_sql` virava `Falha`
    e `extrair_tabela` propagava direto — uma regressão em relação ao
    caminho sequencial, que sempre soube ler essa mesma tabela.
    """
    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(
        extrator_postgres_module.cx,
        "read_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorPostgres(
        dsn=dsn_tabela_grande,
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )

    with caplog.at_level("WARNING"):
        resultado = extrator.extrair_tabela("public", "tabela_grande")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == _N_LINHAS
    assert "leitura paralela via connectorx falhou" in caplog.text
    assert any(
        "leitura paralela via connectorx falhou" in aviso.mensagem
        for aviso in resultado.avisos
    )


def test_leitura_paralela_preserva_consistencia_sob_escrita_concorrente(
    dsn_tabela_grande: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O snapshot exportado protege a leitura paralela de escrita concorrente real.

    Os testes de corretude acima provam que o particionamento por `ctid` é
    exaustivo/disjunto, mas não com escrita concorrente — não distinguem
    "o snapshot funcionou" de "não havia nada pra proteger". Aqui uma
    thread separada fica incrementando `versao` em todas as linhas, sem
    parar, durante toda a extração paralela. Não dá pra garantir *quando*
    exatamente o `pg_export_snapshot()` acontece em relação aos commits da
    thread de escrita — por isso a asserção não é "a amostra tem que
    mostrar versão X", e sim "todas as faixas têm que enxergar a *mesma*
    versão": se o `SET TRANSACTION SNAPSHOT` entre as conexões do
    connectorx estivesse quebrado, faixas diferentes poderiam ler o
    catálogo em momentos diferentes da escrita concorrente, e a amostra
    combinada mostraria uma mistura de versões — corrupção silenciosa,
    sem nenhuma exceção.
    """
    with psycopg2.connect(dsn_tabela_grande) as conexao_setup:
        conexao_setup.autocommit = True
        with conexao_setup.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.tabela_grande "
                "ADD COLUMN IF NOT EXISTS versao INTEGER NOT NULL DEFAULT 1"
            )

    monkeypatch.setattr(paralelismo, "_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA", 0)
    monkeypatch.setattr(paralelismo, "_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA", 0)
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorPostgres(
        dsn=dsn_tabela_grande,
        configuracao=configuracao,
        max_conexoes=8,
        max_conexoes_por_tabela=4,
    )

    parar_escritas = threading.Event()

    def _escrever_sem_parar() -> None:
        conexao_escritora = psycopg2.connect(dsn_tabela_grande)
        conexao_escritora.autocommit = True
        try:
            with conexao_escritora.cursor() as cursor:
                while not parar_escritas.is_set():
                    cursor.execute(
                        "UPDATE public.tabela_grande SET versao = versao + 1"
                    )
        finally:
            conexao_escritora.close()

    thread_escrita = threading.Thread(target=_escrever_sem_parar, daemon=True)
    thread_escrita.start()
    try:
        resultado = extrator.extrair_tabela("public", "tabela_grande")
    finally:
        parar_escritas.set()
        thread_escrita.join(timeout=10)

    assert isinstance(resultado, Sucesso)
    versoes_na_amostra = set(resultado.valor.amostra["versao"].to_list())
    assert len(versoes_na_amostra) == 1, (
        "amostra deveria refletir um único ponto-no-tempo (mesmo snapshot "
        f"em todas as faixas) — versões distintas vistas: {versoes_na_amostra}"
    )

    with psycopg2.connect(dsn_tabela_grande) as conexao_verificacao:
        conexao_verificacao.autocommit = True
        with conexao_verificacao.cursor() as cursor:
            cursor.execute("SELECT MAX(versao) FROM public.tabela_grande")
            (versao_final,) = cursor.fetchone()
    assert versao_final > 1, "escrita concorrente não rodou — teste não provou nada"

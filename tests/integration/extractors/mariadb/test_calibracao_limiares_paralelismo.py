"""Benchmark: calibra os limiares de paralelismo intra-tabela (issue #142).

Mesma calibração de `test_calibracao_limiares_paralelismo.py` (Postgres),
contra MariaDB — os limiares vivem no mesmo módulo motor-agnóstico
(`extractors/comum/leitura_paralela_intra_tabela.py`), mas o mecanismo por
trás é bem diferente: sem conexão líder/snapshot, `K` faixas de PK via
`MIN`/`MAX` (ver Decisão 14 do `system_design_doc.md`) — vale confirmar que
a mesma calibração se sustenta aqui.

Ver `test_calibracao_limiares_paralelismo.py` (Postgres) para o raciocínio
completo dos dois perfis. Mede só tempo, não RSS.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/mariadb/test_calibracao_limiares_paralelismo.py
"""

import subprocess
import sys
from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

pytestmark = pytest.mark.benchmark

_N_ESTREITA_ABAIXO = 350_000
_N_ESTREITA_ACIMA = 650_000

_N_LARGA = 100_000
_BYTES_PAYLOAD_ABAIXO = 4_200
_BYTES_PAYLOAD_ACIMA = 5_800

_USER = "root"
_PASSWORD = "test"
_DATABASE = "calibracao"


def _povoar_estreita(
    conexao: pymysql.connections.Connection, nome: str, n: int
) -> None:
    with conexao.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {nome} (
                id INT PRIMARY KEY,
                categoria INT NOT NULL,
                rotulo VARCHAR(20) NOT NULL
            )
            """
        )
        lote = 5_000
        inicio = 1
        while inicio <= n:
            fim = min(inicio + lote - 1, n)
            valores = ",".join(
                f"({i}, {i % 50}, 'r{i % 1000}')" for i in range(inicio, fim + 1)
            )
            cursor.execute(
                f"INSERT INTO {nome} (id, categoria, rotulo) VALUES {valores}"
            )
            inicio = fim + 1
    conexao.commit()


def _povoar_larga(
    conexao: pymysql.connections.Connection, nome: str, n: int, tamanho_payload: int
) -> None:
    payload = "x" * tamanho_payload
    with conexao.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {nome} (
                id INT PRIMARY KEY,
                payload MEDIUMTEXT NOT NULL
            )
            """
        )
        lote = 200
        inicio = 1
        while inicio <= n:
            fim = min(inicio + lote - 1, n)
            linhas = [(i, payload) for i in range(inicio, fim + 1)]
            cursor.executemany(
                f"INSERT INTO {nome} (id, payload) VALUES (%s, %s)", linhas
            )
            inicio = fim + 1
    conexao.commit()


@pytest.fixture(scope="module")
def conexao_calibracao() -> Iterator[tuple[str, int, str, str, str]]:
    """Sobe um MariaDB descartável com as 4 tabelas de fronteira.

    Returns:
        (host, port, user, password, database).
    """
    with MySqlContainer(
        "mariadb:11", username=_USER, root_password=_PASSWORD, dbname=_DATABASE
    ) as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(container.port))

        conexao = pymysql.connect(
            host=host,
            port=port,
            user=_USER,
            password=_PASSWORD,
            database=_DATABASE,
            autocommit=False,
        )
        try:
            _povoar_estreita(conexao, "estreita_abaixo", _N_ESTREITA_ABAIXO)
            _povoar_estreita(conexao, "estreita_acima", _N_ESTREITA_ACIMA)
            _povoar_larga(conexao, "larga_abaixo", _N_LARGA, _BYTES_PAYLOAD_ABAIXO)
            _povoar_larga(conexao, "larga_acima", _N_LARGA, _BYTES_PAYLOAD_ACIMA)
        finally:
            conexao.close()

        yield host, port, _USER, _PASSWORD, _DATABASE


def _medir_em_subprocesso(
    conexao_info: tuple[str, int, str, str, str], tabela: str, forcar_paralelo: bool
) -> float:
    """Roda extrair_tabela num subprocesso isolado, medindo tempo de parede."""
    host, port, user, password, database = conexao_info
    limiar = 0 if forcar_paralelo else 10**12
    codigo = f"""
import time

import ddf.infrastructure.adapters.extractors.comum.leitura_paralela_intra_tabela \\
    as paralelismo
import ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira as m1
import ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb as m2
import ddf.domain.model.common.configuracao_de_extracao as m3

TabelaInteira = m1.TabelaInteira
ExtratorMariaDB = m2.ExtratorMariaDB
ConfiguracaoDeExtracao = m3.ConfiguracaoDeExtracao

paralelismo._LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA = {limiar}
paralelismo._LIMIAR_BYTES_PARALELISMO_INTRA_TABELA = {limiar}

configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
extrator = ExtratorMariaDB(
    host={host!r}, port={port}, user={user!r}, password={password!r},
    configuracao=configuracao, max_conexoes=8,
)

inicio = time.perf_counter()
resultado = extrator.extrair_tabela({database!r}, {tabela!r})
tempo = time.perf_counter() - inicio

assert resultado.__class__.__name__ == "Sucesso", resultado
print(f"RESULTADO {{tempo}}")
"""
    processo = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    linha_resultado = next(
        linha for linha in processo.stdout.splitlines() if linha.startswith("RESULTADO")
    )
    _, tempo_str = linha_resultado.split()
    return float(tempo_str)


def _comparar(
    conexao_info: tuple[str, int, str, str, str], tabela: str, rotulo: str
) -> None:
    """Mede on/off pra uma tabela e imprime o comparativo."""
    tempo_seq = _medir_em_subprocesso(conexao_info, tabela, forcar_paralelo=False)
    tempo_par = _medir_em_subprocesso(conexao_info, tabela, forcar_paralelo=True)

    print(f"\n--- {rotulo} ({tabela}) ---")
    print(f"sequencial: {tempo_seq:.3f}s | paralelo: {tempo_par:.3f}s")
    print(f"ganho de tempo: {tempo_seq / tempo_par:.2f}x")


def test_calibracao_paralelismo_perfil_estreito_cruza_limiar_de_linhas(
    conexao_calibracao: tuple[str, int, str, str, str],
) -> None:
    """Fronteira do limiar de LINHAS (500.000), perfil estreito (~40 bytes/linha)."""
    _comparar(
        conexao_calibracao,
        "estreita_abaixo",
        f"abaixo ({_N_ESTREITA_ABAIXO} linhas)",
    )
    _comparar(
        conexao_calibracao, "estreita_acima", f"acima ({_N_ESTREITA_ACIMA} linhas)"
    )


def test_calibracao_paralelismo_perfil_largo_cruza_limiar_de_bytes(
    conexao_calibracao: tuple[str, int, str, str, str],
) -> None:
    """Fronteira do limiar de BYTES (500.000.000), perfil largo (linhas fixas)."""
    _comparar(
        conexao_calibracao,
        "larga_abaixo",
        f"abaixo (~{_N_LARGA * _BYTES_PAYLOAD_ABAIXO / 1_000_000:.0f}MB)",
    )
    _comparar(
        conexao_calibracao,
        "larga_acima",
        f"acima (~{_N_LARGA * _BYTES_PAYLOAD_ACIMA / 1_000_000:.0f}MB)",
    )

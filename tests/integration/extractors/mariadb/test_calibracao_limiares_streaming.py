"""Benchmark: calibra `_LIMIAR_LINHAS_STREAMING`/`_LIMIAR_BYTES_STREAMING`.

Mesma calibração de `test_calibracao_limiares_streaming.py` (Postgres),
contra MariaDB — os limiares vivem no mesmo módulo motor-agnóstico
(`extractors/comum/ler_amostra_em_lotes.py`), mas o mecanismo de streaming
por trás (`SSCursor` do `pymysql`) tem custo diferente do cursor nomeado do
Postgres, então vale confirmar que a mesma calibração se sustenta aqui.

Ver `test_calibracao_limiares_streaming.py` (Postgres) para o raciocínio
completo dos dois perfis (estreito/largo) e por que cada um isola um dos
dois critérios do limiar.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts). Rodar
explicitamente:

    uv run pytest -m benchmark -s \
        tests/integration/extractors/mariadb/test_calibracao_limiares_streaming.py
"""

import subprocess
import sys
from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

pytestmark = pytest.mark.benchmark

_N_ESTREITA_ABAIXO = 70_000
_N_ESTREITA_ACIMA = 130_000

_N_LARGA = 40_000
_BYTES_PAYLOAD_ABAIXO = 2_000
_BYTES_PAYLOAD_ACIMA = 3_000


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


_USER = "root"
_PASSWORD = "test"
_DATABASE = "calibracao"


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
    conexao_info: tuple[str, int, str, str, str], tabela: str, forcar_streaming: bool
) -> tuple[float, int]:
    """Roda extrair_tabela num subprocesso isolado, medindo tempo e RSS de pico."""
    host, port, user, password, database = conexao_info
    limiar_linhas = 0 if forcar_streaming else 10**12
    limiar_bytes = 0 if forcar_streaming else 10**15
    codigo = f"""
import resource
import time

import ddf.infrastructure.adapters.extractors.comum.ler_amostra_em_lotes as streaming
import ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira as m1
import ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb as m2
import ddf.domain.model.common.configuracao_de_extracao as m3

TabelaInteira = m1.TabelaInteira
ExtratorMariaDB = m2.ExtratorMariaDB
ConfiguracaoDeExtracao = m3.ConfiguracaoDeExtracao

streaming._LIMIAR_LINHAS_STREAMING = {limiar_linhas}
streaming._LIMIAR_BYTES_STREAMING = {limiar_bytes}

configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
extrator = ExtratorMariaDB(
    host={host!r}, port={port}, user={user!r}, password={password!r},
    configuracao=configuracao,
)

inicio = time.perf_counter()
resultado = extrator.extrair_tabela({database!r}, {tabela!r})
tempo = time.perf_counter() - inicio

assert resultado.__class__.__name__ == "Sucesso", resultado
pico_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"RESULTADO {{tempo}} {{pico_rss_kb}}")
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
    _, tempo_str, pico_rss_str = linha_resultado.split()
    return float(tempo_str), int(pico_rss_str)


def _imprimir_linha(rotulo: str, tempo: float, rss_kb: int) -> None:
    """Formata uma linha da tabela de resultados do benchmark."""
    rss_mb = rss_kb / 1024
    print(f"{rotulo:<28} | {tempo:>8.3f} | {rss_mb:>10.1f}")


def _comparar(
    conexao_info: tuple[str, int, str, str, str], tabela: str, rotulo: str
) -> None:
    """Mede on/off pra uma tabela e imprime o comparativo."""
    tempo_off, rss_off = _medir_em_subprocesso(
        conexao_info, tabela, forcar_streaming=False
    )
    tempo_on, rss_on = _medir_em_subprocesso(
        conexao_info, tabela, forcar_streaming=True
    )

    print(f"\n--- {rotulo} ({tabela}) ---")
    print("configuração                 |  tempo(s) | RSS pico(MB)")
    _imprimir_linha("streaming desligado", tempo_off, rss_off)
    _imprimir_linha("streaming ligado", tempo_on, rss_on)
    variacao_rss = (1 - rss_on / rss_off) * 100
    print(f"variação de RSS ao ligar: {variacao_rss:+.1f}%")


def test_calibracao_streaming_perfil_estreito_cruza_limiar_de_linhas(
    conexao_calibracao: tuple[str, int, str, str, str],
) -> None:
    """Fronteira do limiar de LINHAS (100.000), perfil estreito (~40 bytes/linha)."""
    _comparar(
        conexao_calibracao,
        "estreita_abaixo",
        f"abaixo ({_N_ESTREITA_ABAIXO} linhas)",
    )
    _comparar(
        conexao_calibracao, "estreita_acima", f"acima ({_N_ESTREITA_ACIMA} linhas)"
    )


def test_calibracao_streaming_perfil_largo_cruza_limiar_de_bytes(
    conexao_calibracao: tuple[str, int, str, str, str],
) -> None:
    """Fronteira do limiar de BYTES (100.000.000), perfil largo (linhas fixas)."""
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

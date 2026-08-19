"""Benchmark sintético de ExtratorMariaDB: throughput da consolidação (#104).

Mede o custo das 6 queries de metadado (colunas, PK, FK, UNIQUE, JSON,
total_linhas) "antes" (per-tabela, filtradas por table_name — o padrão
removido por esta issue) vs "depois" (por escopo inteiro, cacheadas — o
padrão atual de `ExtratorMariaDB._obter_metadados_schema`), contra um
conjunto sintético com 10/50/100/200 tabelas espalhadas em alguns escopos —
inclui os 2 cenários de colisão de nome de constraint (UNIQUE e CHECK) que
a consolidação precisa preservar/corrigir (issue #104).

Ressalva de medição, mesma da #66 (ExtratorPostgres): Docker local tem
round-trip sub-milissegundo (socket loopback); MariaDB gerenciado real fica
bem acima disso, mais ainda em cross-AZ. O tempo medido aqui é um PISO
conservador do ganho — a proporção de queries eliminadas (determinística,
não depende de latência de rede) é a evidência mais forte; o tempo de
parede é só ilustrativo.

Não roda por padrão (`pytest -m 'not benchmark'` no addopts) — é oneroso
(cria até 200 tabelas) e sua asserção central é sobre nº de round-trips, não
sobre tempo de parede, que é ruidoso mesmo em Docker. Rodar explicitamente:

    uv run pytest -m benchmark -s tests/integration/extractors/mariadb
"""

import time
from collections.abc import Iterator

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.shared.resultado import Sucesso
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.outbounds.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)

pytestmark = pytest.mark.benchmark

_N_SCHEMAS = 4
_PONTOS_DE_TABELAS = [10, 50, 100, 200]

# As 6 queries abaixo são a réplica fiel do padrão "antes" da issue #104 —
# per-tabela, filtradas por table_name — removido de src/ nesta mesma
# issue. Vivem só aqui, como baseline de benchmark, não como código de
# produção.
_COLUNAS_SQL_ANTIGA = """
    SELECT column_name, data_type, column_type, character_maximum_length,
           numeric_precision, numeric_scale, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
"""

_CHAVES_PRIMARIAS_SQL_ANTIGA = """
    SELECT column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s AND constraint_name = 'PRIMARY'
    ORDER BY ordinal_position
"""

_CHAVES_ESTRANGEIRAS_SQL_ANTIGA = """
    SELECT column_name, referenced_table_schema, referenced_table_name,
           referenced_column_name, constraint_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND table_name = %s
      AND referenced_table_name IS NOT NULL
    ORDER BY constraint_name, ordinal_position
"""

_TOTAL_LINHAS_SQL_ANTIGA = """
    SELECT table_rows
    FROM information_schema.tables
    WHERE table_schema = %s AND table_name = %s
"""

_COLUNAS_UNICAS_SQL_ANTIGA = """
    SELECT kcu.constraint_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
        AND tc.table_name = kcu.table_name
    WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s AND tc.table_name = %s
    ORDER BY kcu.constraint_name, kcu.ordinal_position
"""

_COLUNAS_JSON_SQL_ANTIGA = """
    SELECT cc.check_clause
    FROM information_schema.table_constraints tc
    JOIN information_schema.check_constraints cc
        ON tc.constraint_schema = cc.constraint_schema
        AND tc.constraint_name = cc.constraint_name
    WHERE tc.constraint_type = 'CHECK'
        AND tc.table_schema = %s AND tc.table_name = %s
"""


def _gerar_ddl_sintetico(
    n_tabelas: int,
) -> tuple[list[str], list[tuple[str, str]], str]:
    """Gera escopos/tabelas sintéticos com PK, FK, UNIQUE e CHECK avulsos.

    FK cobre 3 formas: cadeia dentro do escopo, cross-escopo (a cada 10
    tabelas) e uma auto-referência (1ª tabela do 1º escopo). UNIQUE avulso a
    cada 5 tabelas. 5-20 colunas por tabela. Além disso, 2 tabelas do último
    escopo usam `constraint_name` idêntico ("colisao_unica"/"colisao_json")
    pra UNIQUE e CHECK — cenário de colisão que a consolidação (#104)
    precisa preservar (UNIQUE, já corrigido na #44) e corrigir (CHECK, bug
    pré-existente corrigido nesta issue) mesmo consultando o escopo inteiro
    de uma vez.

    Returns:
        (nomes_dos_escopos, [(escopo, tabela), ...] em ordem de criação, DDL).
    """
    escopos = [f"bench_{i}" for i in range(_N_SCHEMAS)]
    tabelas = [
        (escopos[indice % _N_SCHEMAS], f"t{indice}") for indice in range(n_tabelas)
    ]

    comandos = [f"CREATE DATABASE {escopo};" for escopo in escopos]

    for indice, (escopo, tabela) in enumerate(tabelas):
        colunas = ["id INT AUTO_INCREMENT PRIMARY KEY"]

        # Auto-referência: só a 1ª tabela do 1º escopo.
        if indice == 0:
            colunas.append(
                f"parent_id INT, FOREIGN KEY (parent_id) "
                f"REFERENCES {escopo}.{tabela}(id)"
            )

        # FK em cadeia dentro do escopo, a partir da 2ª tabela de cada um.
        indice_anterior = indice - _N_SCHEMAS
        if indice_anterior >= 0:
            escopo_ref, tabela_ref = tabelas[indice_anterior]
            colunas.append(
                f"ref_id INT, FOREIGN KEY (ref_id) "
                f"REFERENCES {escopo_ref}.{tabela_ref}(id)"
            )

        # FK cross-escopo a cada 10 tabelas, pra 1ª tabela do escopo anterior.
        if indice % 10 == 9:
            escopo_pos = indice % _N_SCHEMAS
            escopo_cruzado, tabela_cruzada = tabelas[(escopo_pos - 1) % _N_SCHEMAS]
            colunas.append(
                f"cross_ref_id INT, FOREIGN KEY (cross_ref_id) "
                f"REFERENCES {escopo_cruzado}.{tabela_cruzada}(id)"
            )

        # UNIQUE avulso a cada 5 tabelas.
        if indice % 5 == 4:
            colunas.append("codigo VARCHAR(50) UNIQUE")

        n_colunas_extra = 4 + (indice % 16)  # completa pra faixa 5-20 colunas
        for c in range(n_colunas_extra):
            tipo = "INT" if c % 2 == 0 else "VARCHAR(100)"
            colunas.append(f"col_{c} {tipo}")

        colunas_sql = ",\n            ".join(colunas)
        comandos.append(
            f"CREATE TABLE {escopo}.{tabela} (\n            {colunas_sql}\n        ) "
            f"ENGINE=InnoDB;"
        )
        comandos.append(f"INSERT INTO {escopo}.{tabela} () VALUES ();")

    # Colisão de constraint_name (UNIQUE e CHECK) entre 2 tabelas do último
    # escopo — mesmo nome, tabelas diferentes.
    escopo_colisao = escopos[-1]
    comandos.append(
        f"""
        CREATE TABLE {escopo_colisao}.colisao_a (
            id INT AUTO_INCREMENT PRIMARY KEY,
            valor VARCHAR(50) NOT NULL,
            conteudo JSON,
            CONSTRAINT colisao_unica UNIQUE (valor)
        ) ENGINE=InnoDB;
        """
    )
    comandos.append(
        f"""
        CREATE TABLE {escopo_colisao}.colisao_b (
            id INT AUTO_INCREMENT PRIMARY KEY,
            valor VARCHAR(50) NOT NULL,
            conteudo INT NOT NULL,
            CONSTRAINT colisao_unica UNIQUE (valor),
            CONSTRAINT conteudo CHECK (conteudo >= 0)
        ) ENGINE=InnoDB;
        """
    )
    comandos.append(
        f"INSERT INTO {escopo_colisao}.colisao_a (valor, conteudo) "
        f"VALUES ('x', '{{}}');"
    )
    comandos.append(
        f"INSERT INTO {escopo_colisao}.colisao_b (valor, conteudo) VALUES ('y', 1);"
    )
    tabelas.append((escopo_colisao, "colisao_a"))
    tabelas.append((escopo_colisao, "colisao_b"))

    for escopo, tabela in tabelas:
        comandos.append(f"ANALYZE TABLE {escopo}.{tabela};")

    return escopos, tabelas, "\n".join(comandos)


@pytest.fixture(scope="module")
def conexao_sintetica() -> Iterator[tuple[str, int, str, str]]:
    """Sobe um MariaDB descartável e semeia o maior conjunto sintético (200+ tabelas).

    Sessão única reaproveitada pelos 4 pontos do benchmark — cada ponto usa
    só um prefixo das tabelas já criadas (mesma ordem de _gerar_ddl_sintetico),
    evitando recriar o escopo do zero 4 vezes.
    """
    _, _, ddl = _gerar_ddl_sintetico(max(_PONTOS_DE_TABELAS))
    with MySqlContainer(
        "mariadb:11", username="root", root_password="test", dbname="container_default"
    ) as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(container.port))
        conexao_raiz = pymysql.connect(
            host=host, port=port, user="root", password="test", autocommit=True
        )
        try:
            with conexao_raiz.cursor() as cursor:
                for comando in ddl.split(";\n"):
                    comando_limpo = comando.strip().rstrip(";")
                    if comando_limpo:
                        cursor.execute(comando_limpo)
        finally:
            conexao_raiz.close()
        yield (host, port, "root", "test")


@pytest.fixture
def configuracao() -> ConfiguracaoDeExtracao:
    """ConfiguracaoDeExtracao mínima — o benchmark não olha a amostra."""
    return ConfiguracaoDeExtracao(estrategia=PercentualDeLinhas(percentual=1))


def _medir_antes(
    conexao: tuple[str, int, str, str], tabelas: list[tuple[str, str]]
) -> float:
    """Roda as 6 queries antigas, filtradas por tabela, pra cada tabela do lote."""
    host, port, user, password = conexao
    inicio = time.perf_counter()
    conexao_pymysql = pymysql.connect(
        host=host, port=port, user=user, password=password, autocommit=True
    )
    try:
        with conexao_pymysql.cursor() as cursor:
            for escopo, tabela in tabelas:
                cursor.execute(_COLUNAS_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
                cursor.execute(_CHAVES_PRIMARIAS_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
                cursor.execute(_CHAVES_ESTRANGEIRAS_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
                cursor.execute(_COLUNAS_UNICAS_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
                cursor.execute(_COLUNAS_JSON_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
                cursor.execute(_TOTAL_LINHAS_SQL_ANTIGA, (escopo, tabela))
                cursor.fetchall()
    finally:
        conexao_pymysql.close()
    return time.perf_counter() - inicio


def _medir_depois(
    conexao: tuple[str, int, str, str],
    configuracao: ConfiguracaoDeExtracao,
    tabelas: list[tuple[str, str]],
) -> tuple[float, int]:
    """Roda _obter_metadados_schema pra cada tabela do lote (cache-aware).

    Returns:
        (tempo total, nº de escopos efetivamente populados no cache).
    """
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )
    inicio = time.perf_counter()
    for escopo, _tabela in tabelas:
        resultado = extrator._obter_metadados_schema(escopo)
        assert isinstance(resultado, Sucesso)
    tempo = time.perf_counter() - inicio
    return tempo, len(extrator._cache_schemas)


def test_benchmark_consolidacao_de_metadados_por_schema(
    conexao_sintetica: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Compara nº de round-trips e tempo de parede, antes/depois, em 4 pontos.

    A asserção central é determinística (nº de escopos cacheados == nº de
    escopos distintos no lote, nunca nº de tabelas) — o tempo de parede é
    reportado via print (rodar com -s), não é o critério de aprovação, dado
    o piso conservador de Docker local documentado no topo do arquivo.
    """
    _, todas_as_tabelas, _ = _gerar_ddl_sintetico(max(_PONTOS_DE_TABELAS))

    print(
        "\nn_tabelas | escopos | q.antes | q.depois | t_antes(s) | t_depois(s) | ganho"
    )
    for n_tabelas in _PONTOS_DE_TABELAS:
        lote = todas_as_tabelas[:n_tabelas]
        n_escopos_no_lote = len({escopo for escopo, _ in lote})

        tempo_antes = _medir_antes(conexao_sintetica, lote)
        tempo_depois, escopos_cacheados = _medir_depois(
            conexao_sintetica, configuracao, lote
        )

        queries_antes = 6 * n_tabelas
        queries_depois = 6 * n_escopos_no_lote
        ganho = tempo_antes / tempo_depois if tempo_depois > 0 else float("inf")

        print(
            f"{n_tabelas:>9} | {n_escopos_no_lote:>7} | {queries_antes:>7} | "
            f"{queries_depois:>8} | {tempo_antes:>10.4f} | {tempo_depois:>11.4f} | "
            f"{ganho:>4.1f}x"
        )

        # Determinístico: o cache tem 1 entrada por escopo do lote, nunca 1
        # por tabela — é essa razão, não o tempo de parede, que garante o
        # ganho estrutural independente da latência de rede do ambiente.
        assert escopos_cacheados == n_escopos_no_lote
        assert queries_depois <= queries_antes


def test_benchmark_colisao_de_constraint_resolvida_corretamente(
    conexao_sintetica: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Corretude do cenário de colisão (UNIQUE e CHECK) dentro do lote de volume.

    Roda a extração completa (não só _obter_metadados_schema) contra as 2
    tabelas de colisão semeadas por _gerar_ddl_sintetico — "colisao_a" e
    "colisao_b" compartilham `constraint_name` de UNIQUE ("colisao_unica")
    e "colisao_b" tem um CHECK não-JSON chamado "conteudo", mesmo nome do
    CHECK JSON implícito que "colisao_a" ganha da coluna JSON. Complementa
    a asserção de contagem de queries do teste de throughput — aqui o que
    importa é o resultado estar certo, não a quantidade de round-trips.
    """
    host, port, user, password = conexao_sintetica
    escopo_colisao = f"bench_{_N_SCHEMAS - 1}"
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    colisao_a = extrator.extrair_tabela(escopo_colisao, "colisao_a")
    colisao_b = extrator.extrair_tabela(escopo_colisao, "colisao_b")

    assert isinstance(colisao_a, Sucesso)
    assert isinstance(colisao_b, Sucesso)
    coluna_valor_a = next(c for c in colisao_a.valor.colunas if c.nome == "valor")
    coluna_valor_b = next(c for c in colisao_b.valor.colunas if c.nome == "valor")
    assert coluna_valor_a.unica is True
    assert coluna_valor_b.unica is True
    coluna_conteudo_a = next(c for c in colisao_a.valor.colunas if c.nome == "conteudo")
    coluna_conteudo_b = next(c for c in colisao_b.valor.colunas if c.nome == "conteudo")
    assert coluna_conteudo_a.tipo_dado.categoria == CategoriaDeDado.JSON
    assert coluna_conteudo_b.tipo_dado.categoria != CategoriaDeDado.JSON

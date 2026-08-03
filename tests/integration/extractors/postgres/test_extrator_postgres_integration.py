"""Testes de integração de ExtratorPostgres contra Postgres real (testcontainers)."""

from pathlib import Path

import pytest

from ddf.domain.model.analysis import iniciar_contexto
from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.model.curation import BancoCurado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.analyzers.analisador_de_metricas_de_coluna import (
    AnalisadorDeMetricasDeColuna,
)
from ddf.infrastructure.adapters.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.estrategias.tabela_inteira import (
    TabelaInteira,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)
from ddf.infrastructure.adapters.orchestrator.orquestrador_paralelo import (
    OrquestradorParalelo,
)
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
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
    assert tabela.nome_escopo == "public"
    assert tabela.total_linhas == 3
    assert [coluna.nome for coluna in tabela.colunas] == ["id", "cliente_id", "valor"]

    coluna_id, coluna_fk, coluna_valor = tabela.colunas
    assert coluna_id.chave_primaria is True
    assert coluna_id.unica is False  # PK não é marcada via UNIQUE

    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.nao_nulavel is True
    assert coluna_fk.referencias == [
        ReferenciaDeColuna(
            nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
        )
    ]

    assert coluna_valor.tipo_dado.categoria == CategoriaDeDado.NUMERIC
    assert coluna_valor.tipo_dado.precisao == 10
    assert coluna_valor.tipo_dado.escala == 2
    assert coluna_valor.nao_nulavel is True

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


def test_extrair_tabela_com_coluna_array_mapeia_categoria_e_elemento(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: colunas TEXT[]/INTEGER[] viram ARRAY com elemento correto."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("arrays", "colunas_array")

    assert isinstance(resultado, Sucesso)
    coluna_tags = next(c for c in resultado.valor.colunas if c.nome == "tags")
    coluna_numeros = next(c for c in resultado.valor.colunas if c.nome == "numeros")
    assert coluna_tags.tipo_dado.categoria == CategoriaDeDado.ARRAY
    assert coluna_tags.tipo_dado.elemento == CategoriaDeDado.TEXT
    assert coluna_numeros.tipo_dado.categoria == CategoriaDeDado.ARRAY
    assert coluna_numeros.tipo_dado.elemento == CategoriaDeDado.INTEGER


def test_listar_escopos_retorna_escopos_semeados(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: listar_escopos retorna os schemas semeados, ordenados."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.listar_escopos()

    assert resultado == Sucesso(
        [
            "arrays",
            "colisao_fk",
            "geografia",
            "pessoa",
            "polimorfismo",
            "public",
            "reprodutibilidade",
            "restricoes",
            "rh",
            "truncamento",
            "vazio",
        ]
    )


def test_extrair_duas_tabelas_do_mesmo_schema_reaproveita_cache_de_metadados(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: 2 extrações no mesmo schema (1 instância) trazem dados corretos.

    Prova a corretude da consolidação por schema (issue #66) contra Postgres
    real: a 2ª extração (pedidos) reaproveita o cache de metadados já
    populado pela 1ª (clientes) — mesma instância de ExtratorPostgres, mesmo
    schema — e ainda assim PK/FK/NOT NULL saem corretos pras duas tabelas,
    igual ao caso de instâncias separadas já coberto pelos outros testes.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado_clientes = extrator.extrair_tabela("public", "clientes")
    resultado_pedidos = extrator.extrair_tabela("public", "pedidos")

    assert isinstance(resultado_clientes, Sucesso)
    assert isinstance(resultado_pedidos, Sucesso)

    clientes = resultado_clientes.valor
    assert clientes.total_linhas == 3
    assert [coluna.nome for coluna in clientes.colunas] == [
        "id",
        "nome",
        "criado_em",
    ]
    assert clientes.colunas[0].chave_primaria is True

    pedidos = resultado_pedidos.valor
    assert pedidos.total_linhas == 3
    coluna_fk = pedidos.colunas[1]
    assert coluna_fk.nome == "cliente_id"
    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.referencias == [
        ReferenciaDeColuna(
            nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
        )
    ]


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


def test_extrair_tabela_com_fk_cross_schema_captura_escopo_de_destino(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: FK apontando pra tabela em outro schema preserva o escopo de destino.

    Reproduz o cenário que motivou esta correção (ex.: humanresources.employee
    referenciando person.person no AdventureWorks): rh.funcionario referencia
    pessoa.pessoa, escopo diferente do escopo de origem (rh).
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("rh", "funcionario")

    assert isinstance(resultado, Sucesso)
    coluna_fk = resultado.valor.colunas[1]
    assert coluna_fk.nome == "pessoa_id"
    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.referencias == [
        ReferenciaDeColuna(
            nome_escopo="pessoa", nome_tabela="pessoa", nome_coluna="id"
        )
    ]


def test_listar_tabelas_schema_vazio_retorna_lista_vazia(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: schema real sem tabelas retorna Sucesso com lista vazia."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.listar_tabelas("vazio")

    assert resultado == Sucesso([])


def test_extrair_tabela_com_unique_nomeada_marca_coluna_unica(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: UNIQUE constraint nomeada (single-column) marca unica=True."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("restricoes", "contas")

    assert isinstance(resultado, Sucesso)
    coluna_email = next(c for c in resultado.valor.colunas if c.nome == "email")
    assert coluna_email.unica is True
    assert coluna_email.nao_nulavel is True


def test_extrair_tabela_com_indice_unico_solto_marca_coluna_unica(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: CREATE UNIQUE INDEX sem ADD CONSTRAINT também marca unica=True.

    information_schema.table_constraints (usado pra PK/FK) não lista esse
    índice — só captura via pg_index fecha essa lacuna (achado da banca
    nesta issue: sem isso, 'unica' teria cobertura assimétrica entre
    Postgres e MariaDB para o mesmo padrão real de schema).
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("restricoes", "contas")

    assert isinstance(resultado, Sucesso)
    coluna_apelido = next(c for c in resultado.valor.colunas if c.nome == "apelido")
    assert coluna_apelido.unica is True
    assert coluna_apelido.nao_nulavel is False  # nullable, sem NOT NULL


def test_extrair_tabela_com_unique_composta_nao_marca_colunas_individuais(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: UNIQUE(pais, cep) não torna nenhuma das duas colunas unica=True."""
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("restricoes", "enderecos")

    assert isinstance(resultado, Sucesso)
    coluna_pais = next(c for c in resultado.valor.colunas if c.nome == "pais")
    coluna_cep = next(c for c in resultado.valor.colunas if c.nome == "cep")
    assert coluna_pais.unica is False
    assert coluna_cep.unica is False
    assert coluna_pais.nao_nulavel is True
    assert coluna_cep.nao_nulavel is True
    assert resultado.valor.restricoes_unicas == [
        RestricaoUnica(colunas=("pais", "cep"))
    ]


def test_extrair_tabela_com_indices_especiais_nao_produz_falso_positivo(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: índice de expressão, covering e parcial não viram unica/RestricaoUnica.

    Prova contra Postgres 16 real os 3 bugs bloqueantes achados pela banca
    de revisão da issue #89 — a versão original da query (só filtrando
    array_length(indkey, 1) = 1) teria classificado esses 3 índices
    errado: idx_expressao marcaria col_a como unica=True (JOIN falho na
    entrada de expressão), idx_covering geraria RestricaoUnica(col_c,
    col_a) (col_a é INCLUDE, não faz parte da chave), idx_parcial geraria
    RestricaoUnica(col_a, col_b) mesmo garantindo unicidade só condicional.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("restricoes", "indices_especiais")

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    coluna_a = next(c for c in tabela.colunas if c.nome == "col_a")
    coluna_b = next(c for c in tabela.colunas if c.nome == "col_b")
    coluna_c = next(c for c in tabela.colunas if c.nome == "col_c")

    assert coluna_a.unica is False  # nem via idx_expressao, nem via idx_parcial
    assert coluna_b.unica is False  # nem via idx_parcial
    assert coluna_c.unica is True  # única coluna-chave real de idx_covering
    assert tabela.restricoes_unicas == []  # nenhum dos 3 índices é composto real


def test_extrair_tabela_com_fk_composta_pareia_colunas_corretamente(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: FK composta (2 colunas) não gera produto cartesiano nem Aviso espúrio.

    Reproduz o bug encontrado na revisão da #35 (pré-existente desde a #9):
    o JOIN entre table_constraints/constraint_column_usage casava só por
    constraint_name, sem usar posição — pra FK composta isso gerava produto
    cartesiano (2 colunas locais x 2 colunas referenciadas = 4 linhas em vez
    de 2), com pareamento coluna-local<->coluna-referenciada não garantido.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("geografia", "filial")

    assert isinstance(resultado, Sucesso)
    coluna_codigo = resultado.valor.colunas[1]
    coluna_estado = resultado.valor.colunas[2]
    assert coluna_codigo.nome == "pais_codigo"
    assert coluna_codigo.referencias == [
        ReferenciaDeColuna(
            nome_escopo="geografia", nome_tabela="pais", nome_coluna="codigo"
        )
    ]
    assert coluna_estado.nome == "pais_estado"
    assert coluna_estado.referencias == [
        ReferenciaDeColuna(
            nome_escopo="geografia", nome_tabela="pais", nome_coluna="estado"
        )
    ]
    # Não gera Aviso de FK composta espúrio — só o Aviso de custo, esperado
    # para qualquer extração via PercentualDeLinhas (ver
    # construir_metadados_de_amostra).
    assert len(resultado.avisos) == 1
    assert "varredura sequencial completa" in resultado.avisos[0].mensagem

    # issue #95: as mesmas 2 colunas também formam uma RestricaoDeFkComposta,
    # apontando pra geografia.pais(codigo, estado) — a PK composta real.
    assert resultado.valor.restricoes_fk_compostas == [
        RestricaoDeFkComposta(
            colunas_locais=("pais_codigo", "pais_estado"),
            nome_escopo_referenciado="geografia",
            nome_tabela_referenciada="pais",
            colunas_referenciadas=("codigo", "estado"),
        )
    ]


def test_extrair_tabela_com_fk_de_nome_colidente_resolve_alvo_correto(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: FK de mesmo nome em tabelas diferentes não confunde o alvo (#95).

    Achado da banca de revisão pós-implementação: constraint_name de FK não
    é único por schema no Postgres, só por tabela. `colisao_fk.filho_a` e
    `colisao_fk.filho_b` têm FK nomeada igual (`fk_pai`), cada uma apontando
    pra um alvo diferente (`alvo_a`/`alvo_b`). A query anterior (JOIN por
    nome, sem OID) devolvia o alvo errado/duplicado aqui; a reescrita via
    `pg_catalog` (por `conrelid`/`confrelid`) resolve cada uma
    corretamente.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado_a = extrator.extrair_tabela("colisao_fk", "filho_a")
    resultado_b = extrator.extrair_tabela("colisao_fk", "filho_b")

    assert isinstance(resultado_a, Sucesso)
    assert isinstance(resultado_b, Sucesso)

    coluna_fk_a = next(c for c in resultado_a.valor.colunas if c.nome == "alvo_id")
    coluna_fk_b = next(c for c in resultado_b.valor.colunas if c.nome == "alvo_id")

    assert coluna_fk_a.referencias == [
        ReferenciaDeColuna(
            nome_escopo="colisao_fk", nome_tabela="alvo_a", nome_coluna="id"
        )
    ]
    assert coluna_fk_b.referencias == [
        ReferenciaDeColuna(
            nome_escopo="colisao_fk", nome_tabela="alvo_b", nome_coluna="id"
        )
    ]


def test_extrair_tabela_com_fk_polimorfica_mantem_as_duas_referencias(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Coluna com 2 constraints FK distintas mantém as duas, sem Aviso (#105).

    Contra Postgres real: `polimorfismo.movimentos.entidade_id` tem 2
    constraints FK de coluna única, uma pra `clientes` e outra pra
    `fornecedores` — replica o achado real da issue (MariaDB gerenciado,
    843 tabelas) pra provar que a mudança é agnóstica de fonte.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("polimorfismo", "movimentos")

    assert isinstance(resultado, Sucesso)
    coluna_entidade = next(
        c for c in resultado.valor.colunas if c.nome == "entidade_id"
    )
    assert coluna_entidade.chave_estrangeira is True
    assert coluna_entidade.referencias == [
        ReferenciaDeColuna(
            nome_escopo="polimorfismo", nome_tabela="clientes", nome_coluna="id"
        ),
        ReferenciaDeColuna(
            nome_escopo="polimorfismo", nome_tabela="fornecedores", nome_coluna="id"
        ),
    ]
    # Único Aviso é o de varredura completa da AmostragemProbabilistica
    # (fixture `configuracao`) — nenhum Aviso de FK descartada.
    assert len(resultado.avisos) == 1
    assert "varredura sequencial completa" in resultado.avisos[0].mensagem


def test_coluna_array_com_valores_vazios_e_nulos_nao_quebra_analisador(
    dsn: str, configuracao: ConfiguracaoDeExtracao, tmp_path: Path
) -> None:
    """Borda: array vazio/nulo alimenta o Analisador ponta a ponta sem exceção.

    Reproduz o bug real da auditoria (issue #56): antes da correção,
    `.min()`/`.max()` sobre dtype `pl.List` levantavam
    `polars.exceptions.InvalidOperationError` não capturado por nenhuma
    camada — aqui o pipeline completo (Extrator -> Sobrescrita -> Analisador)
    roda contra a mesma tabela `arrays.colunas_array` do teste de caminho
    feliz, que já tem uma linha com array vazio e uma com array nulo.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)
    resultado_extracao = extrator.extrair_tabela("arrays", "colunas_array")
    assert isinstance(resultado_extracao, Sucesso)

    sobrescrita = SobrescritaDeTabela(tmp_path)
    resultado_curadoria = sobrescrita(resultado_extracao.valor)
    assert isinstance(resultado_curadoria, Sucesso)

    contexto = iniciar_contexto(BancoCurado(tabelas=[resultado_curadoria.valor]))
    resultado_analise = AnalisadorDeMetricasDeColuna()(contexto)

    assert isinstance(resultado_analise, Sucesso)
    tabela_analisada = resultado_analise.valor.analisado.tabelas[0]
    coluna_tags = next(c for c in tabela_analisada.colunas if c.nome == "tags")
    metrica = coluna_tags.metricas[0]
    assert metrica.percentual_nulo == pytest.approx(100 / 3)


def test_extracao_paralela_de_tabelas_do_mesmo_schema_via_orquestrador(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: OrquestradorParalelo real extrai tabelas do mesmo schema em paralelo.

    Contra Postgres real (não mockado), prova que o double-checked locking
    do cache por schema (issue #66) segura sob concorrência de verdade:
    clientes/pedidos são extraídas em threads simultâneas do Orquestrador,
    disputando a 1ª população do cache de `public` — o resultado tem que
    sair correto pras duas, sem corromper nem travar.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao, max_conexoes=4)
    orquestrador = OrquestradorParalelo(max_trabalhadores=4)

    resultado = orquestrador.extrair(["public"], extrator)

    assert isinstance(resultado, Sucesso)
    tabelas = {tabela.nome_tabela: tabela for tabela in resultado.valor}
    assert set(tabelas) == {"clientes", "pedidos"}
    assert tabelas["clientes"].total_linhas == 3
    assert tabelas["pedidos"].total_linhas == 3
    coluna_fk = tabelas["pedidos"].colunas[1]
    assert coluna_fk.referencias == [
        ReferenciaDeColuna(
            nome_escopo="public", nome_tabela="clientes", nome_coluna="id"
        )
    ]


def test_total_linhas_apos_truncate_nao_usa_reltuples_desatualizado(
    dsn: str, configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: TRUNCATE sem novo ANALYZE não deixa total_linhas reportar valor antigo.

    Achado da banca de revisão da issue #76: reltuples (ou até n_live_tup
    sozinho) retém o valor pré-TRUNCATE indefinidamente, sem gatilho de
    autovacuum depois de um TRUNCATE — a query precisa do sinal físico
    (pg_relation_size) pra não mentir aqui. Tabela semeada com 100 linhas,
    ANALYZE, TRUNCATE (setup em conftest.py) — sem isso, reltuples
    reportaria 100 aqui.
    """
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("truncamento", "tabela_truncada")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 0


def test_mesma_seed_produz_a_mesma_amostra(dsn: str) -> None:
    """Borda: duas extrações com o mesmo seed retornam exatamente as mesmas linhas.

    Prova a reprodutibilidade real via TABLESAMPLE ... REPEATABLE contra
    Postgres de verdade — não só que o seed chega na query (isso os testes
    unitários com cursor mockado já cobrem), mas que a garantia documentada
    do Postgres realmente se sustenta. Achado da banca de revisão da issue
    #76: nenhum teste anterior provava isso.
    """
    configuracao = ConfiguracaoDeExtracao(
        estrategia=PercentualDeLinhas(percentual=20, seed=12345)
    )
    extrator_a = ExtratorPostgres(dsn=dsn, configuracao=configuracao)
    extrator_b = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado_a = extrator_a.extrair_tabela("reprodutibilidade", "itens")
    resultado_b = extrator_b.extrair_tabela("reprodutibilidade", "itens")

    assert isinstance(resultado_a, Sucesso)
    assert isinstance(resultado_b, Sucesso)
    ids_a = sorted(resultado_a.valor.amostra["id"].to_list())
    ids_b = sorted(resultado_b.valor.amostra["id"].to_list())
    assert len(ids_a) > 0
    assert ids_a == ids_b


def test_seeds_diferentes_produzem_amostras_diferentes(dsn: str) -> None:
    """Borda: seeds diferentes não convergem pra mesma amostra por acidente.

    Complementa o teste de reprodutibilidade — sem isso, uma implementação
    que ignorasse o seed por completo (bug) passaria no teste de
    "mesma seed, mesma amostra" só por coincidência de sempre montar a
    mesma query.
    """
    extrator_seed_1 = ExtratorPostgres(
        dsn=dsn,
        configuracao=ConfiguracaoDeExtracao(
            estrategia=PercentualDeLinhas(percentual=20, seed=1)
        ),
    )
    extrator_seed_2 = ExtratorPostgres(
        dsn=dsn,
        configuracao=ConfiguracaoDeExtracao(
            estrategia=PercentualDeLinhas(percentual=20, seed=2)
        ),
    )

    resultado_1 = extrator_seed_1.extrair_tabela("reprodutibilidade", "itens")
    resultado_2 = extrator_seed_2.extrair_tabela("reprodutibilidade", "itens")

    assert isinstance(resultado_1, Sucesso)
    assert isinstance(resultado_2, Sucesso)
    ids_1 = sorted(resultado_1.valor.amostra["id"].to_list())
    ids_2 = sorted(resultado_2.valor.amostra["id"].to_list())
    assert ids_1 != ids_2


def test_tabela_inteira_le_a_tabela_toda_sem_tablesample(dsn: str) -> None:
    """Caminho feliz: TabelaInteira contra Postgres real lê 100% das linhas.

    total_linhas exato (len(amostra)) e sem Aviso, mesmo a tabela tendo
    500 linhas reais — prova ponta a ponta que o dispatch AmostragemIntegral
    não depende de TABLESAMPLE/percentual pra ler tudo.
    """
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorPostgres(dsn=dsn, configuracao=configuracao)

    resultado = extrator.extrair_tabela("reprodutibilidade", "itens")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 500
    assert resultado.valor.metadados_amostra.tamanho_amostra == 500
    assert resultado.valor.metadados_amostra.percentual is None
    assert resultado.valor.metadados_amostra.seed is None
    assert resultado.avisos == []

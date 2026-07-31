"""Testes de integração de ExtratorMariaDB contra MariaDB real (testcontainers)."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.infrastructure.adapters.extractors.tabela_inteira import TabelaInteira

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
    assert coluna_id.unica is False  # PK não é marcada via UNIQUE

    assert coluna_fk.chave_estrangeira is True
    assert coluna_fk.nao_nulavel is True
    assert coluna_fk.referencia == ReferenciaDeColuna(
        nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
    )

    assert coluna_valor.tipo_dado.categoria == CategoriaDeDado.NUMERIC
    assert coluna_valor.tipo_dado.precisao == 10
    assert coluna_valor.tipo_dado.escala == 2
    assert coluna_valor.nao_nulavel is True

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


def test_extrair_tabela_mapeia_coluna_json_via_check_clause(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Caminho feliz: coluna JSON real vira CategoriaDeDado.JSON, não TEXT.

    Contra MariaDB real, data_type de uma coluna JSON é "longtext" — a
    classificação correta depende só do CHECK(json_valid(...)) implícito
    (issue #56, validado empiricamente antes desta implementação).
    """
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("restricoes", "pedidos")

    assert isinstance(resultado, Sucesso)
    coluna_metadados = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "metadados"
    )
    assert coluna_metadados.tipo_dado.categoria == CategoriaDeDado.JSON


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

    assert resultado == Sucesso(
        [
            "geografia",
            "pessoa",
            "reprodutibilidade",
            "restricoes",
            "rh",
            "vazio",
            "vendas",
        ]
    )


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


def test_extrair_tabela_com_fk_composta_pareia_colunas_corretamente(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: FK composta (2 colunas) agrupa por CONSTRAINT_NAME sem misturar colunas.

    Mesma fixture do ExtratorPostgres (geografia.pais/filial) — prova que
    o agrupamento via CONSTRAINT_NAME (issue #95) produz a mesma
    RestricaoDeFkComposta correta contra MariaDB real.
    """
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("geografia", "filial")

    assert isinstance(resultado, Sucesso)
    coluna_codigo = next(c for c in resultado.valor.colunas if c.nome == "pais_codigo")
    coluna_estado = next(c for c in resultado.valor.colunas if c.nome == "pais_estado")
    assert coluna_codigo.referencia == ReferenciaDeColuna(
        nome_escopo="geografia", nome_tabela="pais", nome_coluna="codigo"
    )
    assert coluna_estado.referencia == ReferenciaDeColuna(
        nome_escopo="geografia", nome_tabela="pais", nome_coluna="estado"
    )
    assert resultado.valor.restricoes_fk_compostas == [
        RestricaoDeFkComposta(
            colunas_locais=("pais_codigo", "pais_estado"),
            nome_escopo_referenciado="geografia",
            nome_tabela_referenciada="pais",
            colunas_referenciadas=("codigo", "estado"),
        )
    ]


def test_extrair_tabela_com_constraint_de_mesmo_nome_em_outra_tabela_nao_confunde(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: regressão da colisão de nome de UNIQUE constraint entre tabelas.

    "restricoes.pedidos" e "restricoes.clientes" têm UNIQUE KEY "email" com o
    MESMO NOME no MESMO database — nomes de constraint no MySQL/MariaDB são
    escopados por tabela, não por schema. Sem o filtro
    AND kcu.table_name = %s na query de UNIQUE, o JOIN cruzaria as duas
    tabelas e classificaria "email" como não-única por acidente (bug real
    encontrado e reproduzido pela banca durante a revisão desta issue).
    """
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("restricoes", "pedidos")

    assert isinstance(resultado, Sucesso)
    coluna_email = next(c for c in resultado.valor.colunas if c.nome == "email")
    assert coluna_email.unica is True
    assert coluna_email.nao_nulavel is True


def test_extrair_tabela_com_indice_unico_solto_marca_coluna_unica(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: CREATE UNIQUE INDEX sem ADD CONSTRAINT também marca unica=True."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("restricoes", "pedidos")

    assert isinstance(resultado, Sucesso)
    coluna_apelido = next(c for c in resultado.valor.colunas if c.nome == "apelido")
    assert coluna_apelido.unica is True
    assert coluna_apelido.nao_nulavel is False


def test_extrair_tabela_com_unique_composta_nao_marca_colunas_individuais(
    conexao: tuple[str, int, str, str], configuracao: ConfiguracaoDeExtracao
) -> None:
    """Borda: UNIQUE KEY(pais, cep) não torna nenhuma das duas colunas unica=True."""
    host, port, user, password = conexao
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

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


def test_mesma_seed_produz_a_mesma_amostra(
    conexao: tuple[str, int, str, str],
) -> None:
    """Borda: duas extrações com o mesmo seed retornam exatamente as mesmas linhas.

    Prova a reprodutibilidade real via RAND(seed) contra MariaDB de
    verdade — não só que o seed chega na query (isso os testes unitários
    com cursor mockado já cobrem), mas que o determinismo documentado se
    sustenta. Achado da banca de revisão da issue #76: nenhum teste
    anterior provava isso.
    """
    host, port, user, password = conexao
    configuracao = ConfiguracaoDeExtracao(
        estrategia=PercentualDeLinhas(percentual=20, seed=12345)
    )
    extrator_a = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )
    extrator_b = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado_a = extrator_a.extrair_tabela("reprodutibilidade", "itens")
    resultado_b = extrator_b.extrair_tabela("reprodutibilidade", "itens")

    assert isinstance(resultado_a, Sucesso)
    assert isinstance(resultado_b, Sucesso)
    ids_a = sorted(resultado_a.valor.amostra["id"].to_list())
    ids_b = sorted(resultado_b.valor.amostra["id"].to_list())
    assert len(ids_a) > 0
    assert ids_a == ids_b


def test_seeds_diferentes_produzem_amostras_diferentes(
    conexao: tuple[str, int, str, str],
) -> None:
    """Borda: seeds diferentes não convergem pra mesma amostra por acidente.

    Complementa o teste de reprodutibilidade — sem isso, uma implementação
    que ignorasse o seed por completo (bug) passaria no teste de
    "mesma seed, mesma amostra" só por coincidência de sempre montar a
    mesma query.
    """
    host, port, user, password = conexao
    extrator_seed_1 = ExtratorMariaDB(
        host=host,
        port=port,
        user=user,
        password=password,
        configuracao=ConfiguracaoDeExtracao(
            estrategia=PercentualDeLinhas(percentual=20, seed=1)
        ),
    )
    extrator_seed_2 = ExtratorMariaDB(
        host=host,
        port=port,
        user=user,
        password=password,
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


def test_tabela_inteira_le_a_tabela_toda_sem_rand(
    conexao: tuple[str, int, str, str],
) -> None:
    """Caminho feliz: TabelaInteira contra MariaDB real lê 100% das linhas.

    total_linhas exato (len(amostra)) e sem Aviso, mesmo a tabela tendo
    500 linhas reais — prova ponta a ponta que o dispatch AmostragemIntegral
    não depende de RAND()/percentual pra ler tudo.
    """
    host, port, user, password = conexao
    configuracao = ConfiguracaoDeExtracao(estrategia=TabelaInteira())
    extrator = ExtratorMariaDB(
        host=host, port=port, user=user, password=password, configuracao=configuracao
    )

    resultado = extrator.extrair_tabela("reprodutibilidade", "itens")

    assert isinstance(resultado, Sucesso)
    assert resultado.valor.total_linhas == 500
    assert resultado.valor.metadados_amostra.tamanho_amostra == 500
    assert resultado.valor.metadados_amostra.percentual is None
    assert resultado.valor.metadados_amostra.seed is None
    assert resultado.avisos == []

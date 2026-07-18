"""Testes de GeradorMarkdown: caminho feliz, erro de disco e bordas."""

from collections.abc import Callable
from pathlib import Path

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
)
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.generators.gerador_markdown import GeradorMarkdown


def test_caminho_feliz_gera_um_md_por_tabela_e_index(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    metrica_coluna_completa: MetricasBaseColuna,
) -> None:
    """Duas tabelas em escopos diferentes geram arquivos e conteúdo corretos."""
    coluna_a = construir_coluna(
        nome="id",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
        chave_primaria=True,
        metricas=[metrica_coluna_completa],
    )
    tabela_a = construir_tabela(
        colunas=[coluna_a],
        nome_tabela="clientes",
        nome_escopo="vendas",
        total_linhas=1000,
        papel_de_negocio="Cadastro de clientes",
        metricas=[MetricasBaseTabela(completude=95.0)],
    )
    coluna_b = construir_coluna(nome="descricao", metricas=[metrica_coluna_completa])
    tabela_b = construir_tabela(
        colunas=[coluna_b],
        nome_tabela="produtos",
        nome_escopo="estoque",
        metricas=[MetricasBaseTabela(completude=100.0)],
    )
    banco = construir_banco([tabela_a, tabela_b])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo_clientes = (tmp_path / "vendas" / "clientes.md").read_text()
    assert "# vendas.clientes" in conteudo_clientes
    assert "Cadastro de clientes" in conteudo_clientes
    assert "95.00%" in conteudo_clientes
    assert "PK" in conteudo_clientes

    conteudo_index = (tmp_path / "index.md").read_text()
    assert "[clientes](vendas/clientes.md)" in conteudo_index
    assert "[produtos](estoque/produtos.md)" in conteudo_index
    posicao_estoque = conteudo_index.index("estoque")
    posicao_vendas = conteudo_index.index("vendas")
    assert posicao_estoque < posicao_vendas


def test_falha_ao_nao_conseguir_escrever_em_disco(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Destino onde não é possível criar diretório retorna Falha com o path."""
    obstaculo = tmp_path / "vendas"
    obstaculo.write_text("isso deveria ser um diretório, não um arquivo")

    tabela = construir_tabela(
        colunas=[construir_coluna()],
        nome_tabela="clientes",
        nome_escopo="vendas",
    )
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Falha)
    assert str(obstaculo / "clientes.md") in resultado.erro


def test_aviso_para_tabela_sem_papel_de_negocio(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Tabela sem papel_de_negocio gera Aviso, mas ainda é Sucesso."""
    tabela = construir_tabela(colunas=[construir_coluna()], papel_de_negocio=None)
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    assert len(resultado.avisos) == 1
    assert "papel_de_negocio" in resultado.avisos[0].mensagem


def test_metrica_ausente_gera_placeholder_sem_quebrar(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Tabela/coluna sem métrica calculada não derruba o Gerador."""
    coluna_sem_metrica = construir_coluna(nome="sem_metrica", metricas=[])
    tabela_sem_metrica_de_tabela = construir_tabela(
        colunas=[coluna_sem_metrica], metricas=[]
    )
    banco = construir_banco([tabela_sem_metrica_de_tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    assert "N/D" in conteudo


def test_valor_com_pipe_e_escapado_na_tabela_markdown(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Valor de célula com '|' literal não quebra a tabela Markdown."""
    metrica_com_pipe = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=50.0,
        valores_frequentes=[("a|b", 2)],
        minimo="x|y",
        maximo="z",
    )
    coluna = construir_coluna(
        nome="coluna_pipe",
        papel_de_negocio="Campo com | pipe",
        metricas=[metrica_com_pipe],
    )
    tabela = construir_tabela(colunas=[coluna])
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    assert "Campo com \\| pipe" in conteudo
    assert "a\\|b" in conteudo
    linhas_de_tabela = [
        linha for linha in conteudo.splitlines() if linha.startswith("|")
    ]
    for linha in linhas_de_tabela:
        assert linha.count("|") - linha.count("\\|") * 2 >= 2


def test_minimo_e_maximo_suprimidos_para_categoria_textual(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    metrica_coluna_completa: MetricasBaseColuna,
) -> None:
    """VARCHAR não mostra mínimo/máximo (ordenação lexicográfica não é útil)."""
    coluna_texto = construir_coluna(
        nome="nome",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=50),
        metricas=[metrica_coluna_completa],
    )
    coluna_numerica = construir_coluna(
        nome="idade",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.INTEGER),
        metricas=[metrica_coluna_completa],
    )
    tabela = construir_tabela(colunas=[coluna_texto, coluna_numerica])
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
    linhas_qualidade = secao_qualidade.splitlines()
    linha_nome = next(
        linha for linha in linhas_qualidade if linha.startswith("| nome ")
    )
    linha_idade = next(
        linha for linha in linhas_qualidade if linha.startswith("| idade ")
    )
    assert "—" in linha_nome
    assert "1" in linha_idade and "99" in linha_idade


def test_minimo_e_maximo_suprimidos_para_categoria_desconhecida(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """UNKNOWN (ex.: bytea sem categoria mapeada) também suprime mínimo/máximo."""
    metrica_binaria = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=100.0,
        valores_frequentes=[("[dado binário, 32 bytes]", 1)],
        minimo="[dado binário, 32 bytes]",
        maximo="[dado binário, 32 bytes]",
    )
    coluna = construir_coluna(
        nome="spatiallocation",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.UNKNOWN),
        metricas=[metrica_binaria],
    )
    tabela = construir_tabela(colunas=[coluna])
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
    linha = next(
        linha
        for linha in secao_qualidade.splitlines()
        if linha.startswith("| spatiallocation ")
    )
    assert "—" in linha
    assert "dado binário" not in linha


def test_chave_primaria_recebe_aviso_na_secao_de_valores_frequentes(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    metrica_coluna_completa: MetricasBaseColuna,
) -> None:
    """Coluna PK ganha uma nota de baixo sinal analítico junto aos frequentes."""
    coluna_pk = construir_coluna(
        nome="id", chave_primaria=True, metricas=[metrica_coluna_completa]
    )
    coluna_comum = construir_coluna(
        nome="status", metricas=[metrica_coluna_completa]
    )
    tabela = construir_tabela(colunas=[coluna_pk, coluna_comum])
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    secao_id = conteudo.split("#### id")[1].split("#### status")[0]
    secao_status = conteudo.split("#### status")[1]
    assert "chave primária" in secao_id
    assert "chave primária" not in secao_status


def test_coluna_totalmente_nula_recebe_nota_em_vez_de_ser_omitida(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """Coluna 100% nula aparece em Valores frequentes com nota, não some em silêncio."""
    metrica_nula = MetricasBaseColuna(
        percentual_nulo=100.0, percentual_unico=0.0, valores_frequentes=[]
    )
    coluna = construir_coluna(nome="observacao", metricas=[metrica_nula])
    tabela = construir_tabela(colunas=[coluna])
    banco = construir_banco([tabela])

    resultado = GeradorMarkdown()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
    assert "#### observacao" in conteudo
    secao = conteudo.split("#### observacao")[1]
    assert "100% nula" in secao

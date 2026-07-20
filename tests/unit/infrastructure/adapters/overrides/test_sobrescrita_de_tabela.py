"""Testes de SobrescritaDeTabela."""

from pathlib import Path

import yaml

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.model.extraction import ColunaExtraida, TabelaExtraida
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.overrides.sobrescrita_de_tabela import (
    SobrescritaDeTabela,
)

# Caminho feliz


def test_hash_bate_aplica_curadoria_existente(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Caminho feliz: hash bate, aplica papel_de_negocio/regras_de_negocio do YAML."""
    sobrescrita = SobrescritaDeTabela(tmp_path)
    sobrescrita(tabela_extraida)  # gera o skeleton na 1ª execução

    caminho = tmp_path / "public" / "clientes.yaml"
    conteudo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    conteudo["papel_de_negocio"] = "Cadastro de clientes"
    conteudo["colunas"]["nome"]["papel_de_negocio"] = "Nome completo do cliente"
    conteudo["colunas"]["nome"]["regras_de_negocio"] = ["não vazio"]
    caminho.write_text(yaml.safe_dump(conteudo, sort_keys=False), encoding="utf-8")

    resultado = sobrescrita(tabela_extraida)

    assert isinstance(resultado, Sucesso)
    tabela = resultado.valor
    assert tabela.papel_de_negocio == "Cadastro de clientes"
    coluna_nome = next(coluna for coluna in tabela.colunas if coluna.nome == "nome")
    assert coluna_nome.papel_de_negocio == "Nome completo do cliente"
    assert coluna_nome.regras_de_negocio == ["não vazio"]
    assert resultado.avisos == []


# Erro esperado


def test_yaml_malformado_retorna_falha(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Erro esperado: YAML malformado vira Falha com mensagem clara."""
    caminho = tmp_path / "public" / "clientes.yaml"
    caminho.parent.mkdir(parents=True)
    caminho.write_text("hash: [sintaxe inválida\n", encoding="utf-8")

    sobrescrita = SobrescritaDeTabela(tmp_path)
    resultado = sobrescrita(tabela_extraida)

    assert isinstance(resultado, Falha)
    assert "malformada" in resultado.erro


# Borda


def test_arquivo_nao_existe_gera_skeleton_e_aviso(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Borda: 1ª execução sem YAML existente gera skeleton e emite Aviso de criação."""
    sobrescrita = SobrescritaDeTabela(tmp_path)

    resultado = sobrescrita(tabela_extraida)

    assert isinstance(resultado, Sucesso)
    assert len(resultado.avisos) == 1
    assert "criada" in resultado.avisos[0].mensagem
    assert resultado.valor.papel_de_negocio is None

    caminho = tmp_path / "public" / "clientes.yaml"
    assert caminho.exists()
    conteudo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    assert set(conteudo["colunas"].keys()) == {"id", "nome"}


def test_hash_nao_bate_por_coluna_adicionada_preserva_curadoria(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Borda: coluna nova faz hash não bater; curadoria remanescente é preservada."""
    sobrescrita = SobrescritaDeTabela(tmp_path)
    sobrescrita(tabela_extraida)

    caminho = tmp_path / "public" / "clientes.yaml"
    conteudo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    conteudo["colunas"]["nome"]["papel_de_negocio"] = "Nome do cliente"
    caminho.write_text(yaml.safe_dump(conteudo, sort_keys=False), encoding="utf-8")

    coluna_email = ColunaExtraida(
        nome="email",
        tipo_dado=TipoDeDado(categoria=CategoriaDeDado.VARCHAR, tamanho_maximo=200),
    )
    tabela_com_coluna_nova = tabela_extraida.model_copy(
        update={"colunas": [*tabela_extraida.colunas, coluna_email]}
    )

    resultado = sobrescrita(tabela_com_coluna_nova)

    assert isinstance(resultado, Sucesso)
    assert len(resultado.avisos) == 1
    assert "adicionadas: ['email']" in resultado.avisos[0].mensagem

    coluna_nome = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "nome"
    )
    assert coluna_nome.papel_de_negocio == "Nome do cliente"
    nova_coluna = next(
        coluna for coluna in resultado.valor.colunas if coluna.nome == "email"
    )
    assert nova_coluna.papel_de_negocio is None

    conteudo_atualizado = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    assert conteudo_atualizado["hash"] != conteudo["hash"]
    assert set(conteudo_atualizado["colunas"].keys()) == {"id", "nome", "email"}


def test_hash_nao_bate_sem_mudanca_de_nomes_usa_mensagem_generica(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Borda: hash muda por alteração de tipo (nomes preservados) usa msg genérica."""
    sobrescrita = SobrescritaDeTabela(tmp_path)
    sobrescrita(tabela_extraida)

    coluna_nome_com_tipo_novo = tabela_extraida.colunas[1].model_copy(
        update={"tipo_dado": TipoDeDado(categoria=CategoriaDeDado.TEXT)}
    )
    tabela_com_tipo_alterado = tabela_extraida.model_copy(
        update={"colunas": [tabela_extraida.colunas[0], coluna_nome_com_tipo_novo]}
    )

    resultado = sobrescrita(tabela_com_tipo_alterado)

    assert isinstance(resultado, Sucesso)
    assert "algum campo estrutural foi" in resultado.avisos[0].mensagem


def test_hash_muda_quando_coluna_vira_not_null_ou_unique(
    tmp_path: Path, tabela_extraida: TabelaExtraida
) -> None:
    """Borda: nao_nulavel/unica reais do schema entram no hash estrutural.

    Sem isso, uma coluna que virar NOT NULL/UNIQUE no banco não dispararia
    aviso de mudança estrutural nem regeneração do skeleton.
    """
    sobrescrita = SobrescritaDeTabela(tmp_path)
    sobrescrita(tabela_extraida)

    caminho = tmp_path / "public" / "clientes.yaml"
    hash_original = yaml.safe_load(caminho.read_text(encoding="utf-8"))["hash"]

    coluna_nome_agora_unica = tabela_extraida.colunas[1].model_copy(
        update={"nao_nulavel": True, "unica": True}
    )
    tabela_com_restricao_nova = tabela_extraida.model_copy(
        update={"colunas": [tabela_extraida.colunas[0], coluna_nome_agora_unica]}
    )

    resultado = sobrescrita(tabela_com_restricao_nova)

    assert isinstance(resultado, Sucesso)
    assert "algum campo estrutural foi" in resultado.avisos[0].mensagem
    hash_novo = yaml.safe_load(caminho.read_text(encoding="utf-8"))["hash"]
    assert hash_novo != hash_original

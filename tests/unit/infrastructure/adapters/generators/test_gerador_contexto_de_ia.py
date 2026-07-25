"""Testes de GeradorContextoDeIA: caminho feliz, erro esperado e bordas."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    TabelaAnalisada,
)
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.generators.gerador_contexto_de_ia import (
    GeradorContextoDeIA,
)


def _ler_json(caminho: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(caminho.read_text(encoding="utf-8"))


def test_caminho_feliz_gera_index_e_chunk_por_tabela(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Duas tabelas com FK entre elas geram index.json + um chunk cada."""
    coluna_fk = construir_coluna(
        nome="cliente_id",
        chave_estrangeira=True,
        referencia=ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
        ),
    )
    pedidos = construir_tabela(
        colunas=[coluna_fk], nome_tabela="pedidos", nome_escopo="vendas"
    )
    clientes = construir_tabela(
        colunas=[construir_coluna(nome="id", chave_primaria=True)],
        nome_tabela="clientes",
        nome_escopo="vendas",
    )
    banco = construir_banco([pedidos, clientes])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    indice = _ler_json(tmp_path / "index.json")
    assert indice["tabelas"] == [
        {
            "nome_escopo": "vendas",
            "nome_tabela": "clientes",
            "arquivo": "tabelas/vendas__clientes.json",
        },
        {
            "nome_escopo": "vendas",
            "nome_tabela": "pedidos",
            "arquivo": "tabelas/vendas__pedidos.json",
        },
    ]
    grafo = indice["grafo_de_relacionamentos"]
    assert grafo["nota_de_escopo"]
    tabelas_do_grafo = grafo["tabelas"]
    assert tabelas_do_grafo["vendas.pedidos"]["referencia"] == [
        {
            "coluna": "cliente_id",
            "tabela_destino": "vendas.clientes",
            "coluna_destino": "id",
        }
    ]
    assert tabelas_do_grafo["vendas.clientes"]["referenciado_por"] == [
        {
            "tabela_origem": "vendas.pedidos",
            "coluna_origem": "cliente_id",
            "coluna": "id",
        }
    ]
    assert "referenciado_por" not in tabelas_do_grafo["vendas.pedidos"]
    assert "referencia" not in tabelas_do_grafo["vendas.clientes"]

    chunk_pedidos = _ler_json(tmp_path / "tabelas" / "vendas__pedidos.json")
    assert chunk_pedidos["nome_tabela"] == "pedidos"
    assert chunk_pedidos["nome_escopo"] == "vendas"
    assert chunk_pedidos["colunas"][0]["nome"] == "cliente_id"
    assert chunk_pedidos["colunas"][0]["referencia"] == {
        "nome_escopo": "vendas",
        "nome_tabela": "clientes",
        "nome_coluna": "id",
    }


def test_index_registra_generated_at(
    tmp_path: Path,
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
) -> None:
    """index.json registra generated_at no topo (issue #56)."""
    tabela = construir_tabela(colunas=[construir_coluna()])
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    indice = _ler_json(tmp_path / "index.json")
    datetime.fromisoformat(indice["generated_at"])  # levanta ValueError se malformado


def test_falha_ao_nao_conseguir_escrever_em_disco(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Obstáculo no filesystem no lugar do diretório 'tabelas/' força Falha."""
    tabela = construir_tabela(colunas=[construir_coluna()])
    banco = construir_banco([tabela])
    # Cria um arquivo no lugar do diretório "tabelas/" esperado, forçando OSError.
    (tmp_path / "tabelas").write_text("obstaculo", encoding="utf-8")

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Falha)
    assert "tabelas" in resultado.erro


def test_fk_fora_do_lote_aparece_so_como_referencia_de_saida(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """FK apontando pra tabela fora do lote aparece só como referência de saída."""
    coluna_fk = construir_coluna(
        nome="cliente_id",
        chave_estrangeira=True,
        referencia=ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
        ),
    )
    pedidos = construir_tabela(
        colunas=[coluna_fk], nome_tabela="pedidos", nome_escopo="vendas"
    )
    banco = construir_banco([pedidos])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    assert resultado.avisos == []
    indice = _ler_json(tmp_path / "index.json")
    tabelas_do_grafo = indice["grafo_de_relacionamentos"]["tabelas"]
    assert tabelas_do_grafo["vendas.pedidos"]["referencia"] == [
        {
            "coluna": "cliente_id",
            "tabela_destino": "vendas.clientes",
            "coluna_destino": "id",
        }
    ]
    assert "vendas.clientes" not in tabelas_do_grafo


def test_enum_sugerido_quando_cobertura_e_amostra_suficientes(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Coluna categórica com cobertura e amostra suficientes sugere enum."""
    metrica = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=0.03,
        valores_frequentes=[("entregue", 60), ("cancelado", 35)],
    )
    coluna = construir_coluna(nome="status_pedido", metricas=[metrica])
    tabela = construir_tabela(
        colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=100
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    filtraveis = chunk["esquema_de_consulta"]["colunas_filtraveis"]
    assert filtraveis == [
        {
            "coluna": "status_pedido",
            "tipo": "enum",
            "valores": ["entregue", "cancelado"],
            "cobertura_amostral": 0.95,
        }
    ]


def test_amostra_pequena_nao_sugere_enum_mesmo_com_cobertura_total(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Amostra abaixo do piso não sugere enum, mesmo com cobertura de 100%."""
    metrica = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=5.0,
        valores_frequentes=[("a", 10), ("b", 10)],
    )
    coluna = construir_coluna(nome="flag", metricas=[metrica])
    tabela = construir_tabela(
        colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=20
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert "esquema_de_consulta" not in chunk


def test_chave_primaria_nunca_vira_sugestao_de_enum(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Chave primária nunca vira sugestão de enum, mesmo com métricas favoráveis."""
    metrica = MetricasBaseColuna(
        percentual_nulo=0.0,
        percentual_unico=0.03,
        valores_frequentes=[("1", 60), ("2", 35)],
    )
    coluna = construir_coluna(
        nome="id", chave_primaria=True, metricas=[metrica]
    )
    tabela = construir_tabela(
        colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=100
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert "esquema_de_consulta" not in chunk


def test_metadados_amostra_inclui_percentual_e_seed_efetivos(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Caminho feliz: percentual/seed efetivos aparecem no chunk gerado."""
    tabela = construir_tabela(
        colunas=[construir_coluna()],
        nome_tabela="pedidos",
        percentual=10.0,
        seed=42,
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert chunk["metadados_amostra"]["percentual"] == 10.0
    assert chunk["metadados_amostra"]["seed"] == 42


def test_metadados_amostra_percentual_e_seed_sao_none_em_full_scan(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Sem percentual/seed configurados (ex.: full_scan), o chunk traz null."""
    tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert chunk["metadados_amostra"]["percentual"] is None
    assert chunk["metadados_amostra"]["seed"] is None


def test_tabela_sem_metricas_base_tabela_nao_inclui_secao(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Tabela sem MetricasBaseTabela não inclui a seção `metricas_tabela`."""
    tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert "metricas_tabela" not in chunk


def test_tabela_com_metricas_base_tabela_inclui_completude(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Tabela com MetricasBaseTabela inclui `completude` em `metricas_tabela`."""
    tabela = construir_tabela(
        colunas=[construir_coluna()],
        nome_tabela="pedidos",
        metricas=[MetricasBaseTabela(completude=92.4)],
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert chunk["metricas_tabela"] == {"completude": 92.4, "amostra_vazia": False}


def test_amostra_vazia_sinaliza_completude_sem_evidencia(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Borda: tamanho_amostra == 0 marca amostra_vazia=True junto da completude.

    completude=100.0 é o mesmo valor numérico de uma tabela genuinamente
    completa — sem essa flag, um agente consumidor não tem como distinguir
    os dois casos (issue #56).
    """
    tabela = construir_tabela(
        colunas=[construir_coluna()],
        nome_tabela="pedidos",
        tamanho_amostra=0,
        metricas=[MetricasBaseTabela(completude=100.0)],
    )
    banco = construir_banco([tabela])

    resultado = GeradorContextoDeIA()(banco, tmp_path)

    assert isinstance(resultado, Sucesso)
    chunk = _ler_json(tmp_path / "tabelas" / "escopo__pedidos.json")
    assert chunk["metricas_tabela"] == {"completude": 100.0, "amostra_vazia": True}


def test_geracao_e_deterministica(
    construir_coluna: Callable[..., ColunaAnalisada],
    construir_tabela: Callable[..., TabelaAnalisada],
    construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    tmp_path: Path,
) -> None:
    """Gerar duas vezes o mesmo BancoAnalisado produz JSONs idênticos byte-a-byte.

    `index.json` é comparado à parte, excluindo `generated_at` — esse campo
    captura o momento da geração de propósito (issue #56), então difere
    entre as duas execuções mesmo com entrada idêntica; o resto do arquivo
    (e o chunk por tabela, que não carrega esse campo) continua
    determinístico.
    """
    coluna_fk = construir_coluna(
        nome="cliente_id",
        chave_estrangeira=True,
        referencia=ReferenciaDeColuna(
            nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
        ),
    )
    pedidos = construir_tabela(
        colunas=[coluna_fk], nome_tabela="pedidos", nome_escopo="vendas"
    )
    clientes = construir_tabela(
        colunas=[construir_coluna(nome="id", chave_primaria=True)],
        nome_tabela="clientes",
        nome_escopo="vendas",
    )
    banco = construir_banco([pedidos, clientes])

    destino_a = tmp_path / "a"
    destino_b = tmp_path / "b"
    resultado_a = GeradorContextoDeIA()(banco, destino_a)
    resultado_b = GeradorContextoDeIA()(banco, destino_b)

    assert isinstance(resultado_a, Sucesso)
    assert isinstance(resultado_b, Sucesso)
    indice_a = _ler_json(destino_a / "index.json")
    indice_b = _ler_json(destino_b / "index.json")
    assert "generated_at" in indice_a
    del indice_a["generated_at"]
    del indice_b["generated_at"]
    assert indice_a == indice_b
    assert (destino_a / "tabelas" / "vendas__pedidos.json").read_text(
        encoding="utf-8"
    ) == (destino_b / "tabelas" / "vendas__pedidos.json").read_text(encoding="utf-8")

"""Testes de GeradorContextoDeIA: caminho feliz, erro esperado e bordas."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ddf.domain.model.analysis import (
    BancoAnalisado,
    ColunaAnalisada,
    MetricasBaseColuna,
    MetricasBaseTabela,
    MetricasDeConfianca,
    NivelDeConfianca,
    TabelaAnalisada,
)
from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.model.common.restricao_de_fk_composta import RestricaoDeFkComposta
from ddf.domain.model.common.restricao_unica import RestricaoUnica
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.infrastructure.adapters.outbounds.generators.contexto_de_ia.gerador_contexto_de_ia import (  # noqa: E501
    GeradorContextoDeIA,
)


def _ler_json(caminho: Path) -> dict[str, Any]:
    conteudo: dict[str, Any] = json.loads(caminho.read_text(encoding="utf-8"))
    return conteudo


class TestFeliz:
    """Caminho feliz."""

    def test_caminho_feliz_gera_index_e_chunk_por_tabela(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Duas tabelas com FK entre elas geram index.json + um chunk cada."""
        coluna_fk = construir_coluna(
            nome="cliente_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
            ],
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
                "arquivo": "tabelas/vendas/clientes.json",
            },
            {
                "nome_escopo": "vendas",
                "nome_tabela": "pedidos",
                "arquivo": "tabelas/vendas/pedidos.json",
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

        chunk_pedidos = _ler_json(tmp_path / "tabelas" / "vendas" / "pedidos.json")
        assert chunk_pedidos["nome_tabela"] == "pedidos"
        assert chunk_pedidos["nome_escopo"] == "vendas"
        assert chunk_pedidos["colunas"][0]["nome"] == "cliente_id"
        assert chunk_pedidos["colunas"][0]["referencias"] == [
            {
                "nome_escopo": "vendas",
                "nome_tabela": "clientes",
                "nome_coluna": "id",
            }
        ]

    def test_index_registra_generated_at(
        self,
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
        datetime.fromisoformat(
            indice["generated_at"]
        )  # levanta ValueError se malformado

    def test_fk_fora_do_lote_aparece_so_como_referencia_de_saida(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """FK apontando pra tabela fora do lote aparece só como referência de saída."""
        coluna_fk = construir_coluna(
            nome="cliente_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
            ],
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
        self,
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
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
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
        self,
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
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "esquema_de_consulta" not in chunk

    def test_timestamp_nunca_sugere_enum_mesmo_com_cobertura_total(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """TIMESTAMP nunca sugere enum, mesmo com cobertura/cardinalidade boas (#95).

        Datas são monotônicas por natureza — nenhuma amostra torna um "criado
        em" um universo fechado, mesmo que a amostra pequena só tenha visto 2
        valores literais.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=2.0,
            valores_frequentes=[
                ("2024-01-01T00:00:00", 60),
                ("2024-01-02T00:00:00", 40),
            ],
        )
        coluna = construir_coluna(
            nome="criado_em",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP),
            metricas=[metrica],
        )
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=100
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "esquema_de_consulta" not in chunk

    def test_exatamente_dez_distintos_reconstruidos_nao_sugere_enum(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Teto de cardinalidade pega o que `percentual_unico<10` sozinho não pega.

        200 linhas, `percentual_unico=5.0` (< 10, passaria no critério antigo),
        mas a contagem de distintos reconstruída (`200 * 0.05 = 10`) bate o
        teto — a lista de `valores_frequentes` (truncada em 10) não distingue
        "tem exatamente 10 distintos" de "tem 200 e só vemos os 10 mais
        frequentes", então o teto de cardinalidade real evita a enumeração.
        """
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=5.0,
            valores_frequentes=[(str(v), 20) for v in range(10)],
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=200
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "esquema_de_consulta" not in chunk

    def test_nove_distintos_com_amostra_e_cobertura_ok_sugere_enum(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Abaixo do teto de cardinalidade, amostra e cobertura ok, ainda sugere (#95).

        200 linhas, `percentual_unico=4.5` reconstrói pra 9 distintos — abaixo
        do teto de 10 — e os 9 valores cobrem 190/200 (95%) da amostra.
        """
        valores_frequentes = [(str(v), 21) for v in range(8)] + [("8", 22)]
        metrica = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=4.5,
            valores_frequentes=valores_frequentes,
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=200
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        filtraveis = chunk["esquema_de_consulta"]["colunas_filtraveis"]
        assert filtraveis[0]["coluna"] == "codigo"

    def test_alta_cardinalidade_real_mascarada_por_nulos_nao_sugere_enum(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Regressão: nulos não podem mascarar cardinalidade real alta (#95).

        1000 linhas, 90% nulas (100 não-nulas), `percentual_unico=6.0` — a
        contagem real de distintos é `1000 * 0.06 = 60`, bem acima do teto de
        10. A fórmula antiga de `_contagem_de_distintos` multiplicava de novo
        pelo não-nulo (`100 * 0.06 = 6`), passando incorretamente no teto de
        cardinalidade só porque a coluna tem muitos nulos.
        """
        valores_frequentes = [(str(v), 9) for v in range(9)] + [("9", 14)]
        metrica = MetricasBaseColuna(
            percentual_nulo=90.0,
            percentual_unico=6.0,
            valores_frequentes=valores_frequentes,
        )
        coluna = construir_coluna(nome="codigo", metricas=[metrica])
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=1000
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "esquema_de_consulta" not in chunk

    def test_chave_primaria_nunca_vira_sugestao_de_enum(
        self,
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
        coluna = construir_coluna(nome="id", chave_primaria=True, metricas=[metrica])
        tabela = construir_tabela(
            colunas=[coluna], nome_tabela="pedidos", tamanho_amostra=100
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "esquema_de_consulta" not in chunk

    def test_metadados_amostra_inclui_percentual_e_seed_efetivos(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """percentual/seed efetivos aparecem no chunk gerado."""
        tabela = construir_tabela(
            colunas=[construir_coluna()],
            nome_tabela="pedidos",
            percentual=10.0,
            seed=42,
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["metadados_amostra"]["percentual"] == 10.0
        assert chunk["metadados_amostra"]["seed"] == 42

    def test_metadados_amostra_percentual_e_seed_sao_none_em_tabela_inteira(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Sem percentual/seed configurados (ex.: tabela_inteira), o chunk traz null."""
        tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["metadados_amostra"]["percentual"] is None
        assert chunk["metadados_amostra"]["seed"] is None

    def test_tabela_sem_metricas_base_tabela_nao_inclui_secao(
        self,
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
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "metricas_tabela" not in chunk

    def test_tabela_com_metricas_base_tabela_inclui_completude(
        self,
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
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["metricas_tabela"] == {"completude": 92.4, "amostra_vazia": False}

    def test_tabela_com_metricas_de_confianca_inclui_confianca_no_chunk(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """MetricasDeConfianca vira `confianca` dentro de `metricas_tabela`."""
        tabela = construir_tabela(
            colunas=[construir_coluna()],
            nome_tabela="pedidos",
            metricas=[
                MetricasBaseTabela(completude=92.4),
                MetricasDeConfianca(nivel=NivelDeConfianca.MEDIA),
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["metricas_tabela"] == {
            "completude": 92.4,
            "amostra_vazia": False,
            "confianca": "media",
        }

    def test_metricas_tabela_sem_confianca_nao_inclui_a_chave(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """MetricasBaseTabela sem MetricasDeConfianca não gera a chave `confianca`."""
        tabela = construir_tabela(
            colunas=[construir_coluna()],
            nome_tabela="pedidos",
            metricas=[MetricasBaseTabela(completude=92.4)],
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "confianca" not in chunk["metricas_tabela"]

    def test_restricoes_unicas_presente_e_ordenada_no_chunk(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """UNIQUE composto aparece como lista de listas, ordenada por colunas."""
        tabela = construir_tabela(
            colunas=[construir_coluna(nome="loja_id"), construir_coluna(nome="sku")],
            nome_tabela="estoque_por_loja",
            restricoes_unicas=[
                RestricaoUnica(colunas=("sku", "loja_id")),
                RestricaoUnica(colunas=("loja_id", "sku")),
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "estoque_por_loja.json")
        assert chunk["restricoes_unicas"] == [
            ["loja_id", "sku"],
            ["sku", "loja_id"],
        ]

    def test_restricoes_fk_compostas_presente_e_ordenada_no_chunk(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """FK composta aparece como lista de dicts, ordenada por colunas_locais."""
        tabela = construir_tabela(
            colunas=[
                construir_coluna(nome="pais_id"),
                construir_coluna(nome="estado_id"),
            ],
            nome_tabela="pedidos",
            restricoes_fk_compostas=[
                RestricaoDeFkComposta(
                    colunas_locais=("pais_id", "estado_id"),
                    nome_escopo_referenciado="geografia",
                    nome_tabela_referenciada="estados",
                    colunas_referenciadas=("pais_id", "id"),
                )
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["restricoes_fk_compostas"] == [
            {
                "colunas_locais": ["pais_id", "estado_id"],
                "escopo_referenciado": "geografia",
                "tabela_referenciada": "estados",
                "colunas_referenciadas": ["pais_id", "id"],
            }
        ]

    def test_geracao_e_deterministica(
        self,
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
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
            ],
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
        assert (destino_a / "tabelas" / "vendas" / "pedidos.json").read_text(
            encoding="utf-8"
        ) == (destino_b / "tabelas" / "vendas" / "pedidos.json").read_text(
            encoding="utf-8"
        )


class TestErro:
    """Erro esperado."""

    def test_falha_ao_nao_conseguir_escrever_em_disco(
        self,
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


class TestBorda:
    """Bordas."""

    def test_amostra_vazia_sinaliza_completude_sem_evidencia(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """tamanho_amostra == 0 marca amostra_vazia=True junto da completude.

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
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert chunk["metricas_tabela"] == {"completude": 100.0, "amostra_vazia": True}

    def test_restricoes_unicas_ausente_omite_chave(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Tabela sem UNIQUE composto não inclui a chave `restricoes_unicas`."""
        tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "restricoes_unicas" not in chunk

    def test_restricoes_fk_compostas_ausente_omite_chave(
        self,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        tmp_path: Path,
    ) -> None:
        """Tabela sem FK composta não inclui a chave `restricoes_fk_compostas`."""
        tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
        banco = construir_banco([tabela])

        resultado = GeradorContextoDeIA()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        chunk = _ler_json(tmp_path / "tabelas" / "escopo" / "pedidos.json")
        assert "restricoes_fk_compostas" not in chunk

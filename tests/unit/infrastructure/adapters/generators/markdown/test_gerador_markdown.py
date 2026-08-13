"""Testes de GeradorMarkdown: caminho feliz, erro de disco e bordas."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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
from ddf.infrastructure.adapters.generators.markdown.gerador_markdown import (
    GeradorMarkdown,
)


class TestFeliz:
    """Caminho feliz."""

    def test_caminho_feliz_gera_um_md_por_tabela_e_index(
        self,
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
        coluna_b = construir_coluna(
            nome="descricao", metricas=[metrica_coluna_completa]
        )
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

    def test_rodape_mostra_percentual_e_seed_quando_presentes(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """percentual/seed efetivos aparecem no rodapé de amostragem do .md."""
        tabela = construir_tabela(
            colunas=[construir_coluna()],
            nome_tabela="pedidos",
            percentual=10.0,
            seed=42,
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "pedidos.md").read_text()
        assert "(10.0%)" in conteudo
        assert "seed `42`" in conteudo
        assert "métricas de coluna são estimativas sobre a amostra" in conteudo

    def test_rodape_omite_percentual_e_seed_em_tabela_inteira(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Sem percentual/seed, o rodapé não os menciona nem mente sobre estimativa.

        Sem essa condicional, o rodapé afirmaria "métricas são estimativas
        sobre a amostra, não o dado completo" mesmo quando a amostra JÁ é o
        dado completo (tabela_inteira) — achado da banca de revisão da #76.
        """
        tabela = construir_tabela(colunas=[construir_coluna()], nome_tabela="pedidos")
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "pedidos.md").read_text()
        assert "seed" not in conteudo
        assert "%)" not in conteudo
        assert "estimativas sobre a amostra" not in conteudo
        assert (
            "leitura completa da tabela, métricas de coluna refletem o dado real"
            in (conteudo)
        )

    def test_index_e_tabela_registram_generated_at(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """index.md e o .md por tabela registram o momento da geração (issue #56).

        Sem timestamp, um snapshot estático não dá ao humano nem ao agente de
        IA como julgar frescor do artefato.
        """
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        for conteudo in (
            (tmp_path / "escopo" / "tabela.md").read_text(),
            (tmp_path / "index.md").read_text(),
        ):
            linha = next(
                linha
                for linha in conteudo.splitlines()
                if linha.startswith("*Gerado em:")
            )
            timestamp = linha.removeprefix("*Gerado em: ").removesuffix("*")
            datetime.fromisoformat(timestamp)  # levanta ValueError se malformado

    def test_aviso_para_tabela_sem_papel_de_negocio(
        self,
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

    def test_varias_tabelas_sem_papel_de_negocio_colapsam_em_um_aviso(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Várias tabelas sem papel_de_negocio geram um único Aviso com a contagem."""
        tabelas = [
            construir_tabela(
                colunas=[construir_coluna()],
                nome_tabela=f"tabela_{i}",
                papel_de_negocio=None,
            )
            for i in range(3)
        ]
        banco = construir_banco(tabelas)

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        assert len(resultado.avisos) == 1
        assert resultado.avisos[0].mensagem == "3 tabela(s) sem papel_de_negocio."

    def test_metrica_ausente_gera_placeholder_sem_quebrar(
        self,
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
        self,
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
        self,
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
        self,
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
        self,
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

    def test_coluna_nao_nulavel_mostra_garantido_pelo_schema(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """NOT NULL real do schema aparece anotado, distinto do percentual amostral.

        A mesma garantia também aparece como marcador "NOT NULL" na seção
        Colunas (coluna "Restrição") — não fica visível só dentro do texto da
        Qualidade dos dados.
        """
        coluna_not_null = construir_coluna(
            nome="cpf", nao_nulavel=True, metricas=[metrica_coluna_completa]
        )
        coluna_comum = construir_coluna(
            nome="apelido", metricas=[metrica_coluna_completa]
        )
        tabela = construir_tabela(colunas=[coluna_not_null, coluna_comum])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()

        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_restricao_cpf = next(
            linha for linha in secao_colunas.splitlines() if "cpf" in linha
        )
        linha_restricao_apelido = next(
            linha for linha in secao_colunas.splitlines() if "apelido" in linha
        )
        assert "NOT NULL" in linha_restricao_cpf
        assert "NOT NULL" not in linha_restricao_apelido

        secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
        linha_cpf = next(
            linha
            for linha in secao_qualidade.splitlines()
            if linha.startswith("| cpf ")
        )
        linha_apelido = next(
            linha
            for linha in secao_qualidade.splitlines()
            if linha.startswith("| apelido ")
        )
        assert "garantido pelo schema" in linha_cpf
        assert "garantido pelo schema" not in linha_apelido
        assert "10.00%" in linha_apelido  # percentual_nulo amostral, sem anotação

    def test_coluna_unica_recebe_marcador_e_aviso_de_baixo_sinal(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """UNIQUE real do schema ganha marcador na tabela e nota nos frequentes."""
        coluna_unica = construir_coluna(
            nome="email", unica=True, metricas=[metrica_coluna_completa]
        )
        tabela = construir_tabela(colunas=[coluna_unica])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_email = next(
            linha for linha in secao_colunas.splitlines() if "email" in linha
        )
        assert "UNIQUE" in linha_email
        secao_frequentes = conteudo.split("#### email")[1]
        assert "restrição UNIQUE" in secao_frequentes

    def test_coluna_pk_e_unica_nao_duplica_marcador_nem_aviso(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """PK também unica/nao_nulavel (redundância do schema) não duplica sinal."""
        coluna_pk = construir_coluna(
            nome="id",
            chave_primaria=True,
            unica=True,
            nao_nulavel=True,
            metricas=[metrica_coluna_completa],
        )
        tabela = construir_tabela(colunas=[coluna_pk])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_id = next(linha for linha in secao_colunas.splitlines() if "id" in linha)
        assert "PK" in linha_id
        assert "UNIQUE" not in linha_id
        assert "NOT NULL" not in linha_id
        secao_frequentes = conteudo.split("#### id")[1]
        assert "chave primária" in secao_frequentes
        assert "restrição UNIQUE" not in secao_frequentes

    def test_coluna_fk_e_unica_combina_os_dois_marcadores(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """FK 1:1 (também unica=True) mostra FK e UNIQUE combinados."""
        coluna_fk_unica = construir_coluna(
            nome="perfil_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="rh", nome_tabela="perfis", nome_coluna="id"
                ),
            ],
            unica=True,
            metricas=[metrica_coluna_completa],
        )
        tabela = construir_tabela(colunas=[coluna_fk_unica])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_perfil = next(
            linha for linha in secao_colunas.splitlines() if "perfil_id" in linha
        )
        assert "FK → rh.perfis.id" in linha_perfil
        assert "UNIQUE" in linha_perfil

    def test_coluna_com_fk_polimorfica_mostra_um_marcador_por_referencia(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """Coluna com 2+ FKs distintas (#105) mostra um "FK → ..." por referência."""
        coluna_fk_polimorfica = construir_coluna(
            nome="entidade_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="clientes", nome_coluna="id"
                ),
                ReferenciaDeColuna(
                    nome_escopo="vendas", nome_tabela="fornecedores", nome_coluna="id"
                ),
            ],
            metricas=[metrica_coluna_completa],
        )
        tabela = construir_tabela(colunas=[coluna_fk_polimorfica])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_entidade = next(
            linha for linha in secao_colunas.splitlines() if "entidade_id" in linha
        )
        assert "FK → vendas.clientes.id" in linha_entidade
        assert "FK → vendas.fornecedores.id" in linha_entidade

    def test_minimo_e_maximo_suprimidos_para_categoria_json(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """JSON/JSONB também suprime mínimo/máximo (mesmo bug corrigido nas outras)."""
        metrica_json = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=100.0,
            valores_frequentes=[('{"a": 1}', 1)],
            minimo='{"a": 1, "z": 9}',
            maximo='{"b": 0}',
        )
        coluna = construir_coluna(
            nome="metadados",
            tipo_dado=TipoDeDado(categoria=CategoriaDeDado.JSON),
            metricas=[metrica_json],
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
            if linha.startswith("| metadados ")
        )
        assert "—" in linha
        assert '{"a": 1' not in linha

    def test_array_renderiza_elemento_e_suprime_minimo_e_maximo(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """ARRAY mostra 'INTEGER[]' na tabela de Colunas e some de Mínimo/Máximo."""
        metrica_array = MetricasBaseColuna(
            percentual_nulo=0.0,
            percentual_unico=100.0,
            valores_frequentes=[("['a', 'b']", 1)],
            minimo="['a', 'b']",
            maximo="['z']",
        )
        coluna = construir_coluna(
            nome="tags",
            tipo_dado=TipoDeDado(
                categoria=CategoriaDeDado.ARRAY, elemento=CategoriaDeDado.INTEGER
            ),
            metricas=[metrica_array],
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_colunas = next(
            linha for linha in secao_colunas.splitlines() if "tags" in linha
        )
        assert "INTEGER[]" in linha_colunas

        secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
        linha_qualidade = next(
            linha
            for linha in secao_qualidade.splitlines()
            if linha.startswith("| tags ")
        )
        assert "—" in linha_qualidade
        assert "['a', 'b']" not in linha_qualidade

    def test_coluna_totalmente_nula_recebe_nota_em_vez_de_ser_omitida(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna 100% nula aparece em Valores frequentes com nota, não some calada."""
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

    def test_restricoes_unicas_composta_aparece_em_fatos_extraidos(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """UNIQUE composto aparece como bullet em Fatos extraídos, grupos ordenados."""
        coluna_a = construir_coluna(nome="loja_id")
        coluna_b = construir_coluna(nome="sku")
        tabela = construir_tabela(
            colunas=[coluna_a, coluna_b],
            restricoes_unicas=[
                RestricaoUnica(colunas=("sku", "loja_id")),
                RestricaoUnica(colunas=("loja_id", "sku")),
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_fatos = conteudo.split("## Fatos extraídos")[1].split("## Colunas")[0]
        assert "Restrições UNIQUE compostas" in secao_fatos
        assert (
            "(`loja_id`, `sku`), (`sku`, `loja_id`)" in secao_fatos
        )  # ordenado por tupla, não pela ordem de origem

    def test_coluna_em_restricao_composta_recebe_marcador_na_tabela_de_colunas(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna participante de UNIQUE composto ganha marcador na coluna Restrição."""
        coluna_composta = construir_coluna(nome="loja_id")
        coluna_fora = construir_coluna(nome="descricao")
        tabela = construir_tabela(
            colunas=[coluna_composta, coluna_fora],
            restricoes_unicas=[RestricaoUnica(colunas=("loja_id", "sku"))],
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_loja_id = next(
            linha for linha in secao_colunas.splitlines() if "loja_id" in linha
        )
        linha_descricao = next(
            linha for linha in secao_colunas.splitlines() if "descricao" in linha
        )
        assert "UNIQUE (composto)" in linha_loja_id
        assert "UNIQUE (composto)" not in linha_descricao

    def test_restricoes_fk_compostas_aparece_em_fatos_extraidos(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """FK composta aparece como bullet em Fatos extraídos, grupos ordenados."""
        coluna_pais = construir_coluna(
            nome="pais_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="geografia",
                    nome_tabela="estados",
                    nome_coluna="pais_id",
                ),
            ],
        )
        coluna_estado = construir_coluna(
            nome="estado_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="geografia", nome_tabela="estados", nome_coluna="id"
                ),
            ],
        )
        tabela = construir_tabela(
            colunas=[coluna_pais, coluna_estado],
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

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_fatos = conteudo.split("## Fatos extraídos")[1].split("## Colunas")[0]
        assert "Chaves estrangeiras compostas" in secao_fatos
        assert (
            "(`pais_id`, `estado_id`) → geografia.estados(`pais_id`, `id`)"
            in secao_fatos
        )

    def test_coluna_em_fk_composta_recebe_marcador_sem_substituir_fk_individual(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Coluna em FK composta ganha "FK (composta)" mantendo "FK → ..."."""
        coluna_pais = construir_coluna(
            nome="pais_id",
            chave_estrangeira=True,
            referencias=[
                ReferenciaDeColuna(
                    nome_escopo="geografia",
                    nome_tabela="estados",
                    nome_coluna="pais_id",
                ),
            ],
        )
        coluna_fora = construir_coluna(nome="descricao")
        tabela = construir_tabela(
            colunas=[coluna_pais, coluna_fora],
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

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_pais_id = next(
            linha for linha in secao_colunas.splitlines() if "pais_id" in linha
        )
        linha_descricao = next(
            linha for linha in secao_colunas.splitlines() if "descricao" in linha
        )
        assert "FK (composta)" in linha_pais_id
        assert "FK → geografia.estados.pais_id" in linha_pais_id
        assert "FK (composta)" not in linha_descricao

    def test_secao_de_valores_frequentes_vazia_explica_o_motivo(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Tabela sem nenhuma coluna elegível ainda mostra o cabeçalho + uma nota.

        Cenário real: amostra vazia (tabela sem linhas extraídas) faz toda
        coluna cair fora de _secoes_valores_frequentes — sem a nota, a seção
        inteira desaparecia em silêncio, parecendo um bug de geração.
        """
        coluna_sem_metrica = construir_coluna(nome="id", metricas=[])
        tabela = construir_tabela(colunas=[coluna_sem_metrica], tamanho_amostra=0)
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        assert "## Valores frequentes por coluna" in conteudo
        secao = conteudo.split("## Valores frequentes por coluna")[1]
        assert "Nenhuma coluna desta tabela tem valores frequentes elegíveis" in secao


class TestErro:
    """Erro esperado."""

    def test_falha_ao_nao_conseguir_escrever_em_disco(
        self,
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


class TestBorda:
    """Bordas."""

    def test_array_sem_elemento_reconhecido_renderiza_unknown(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """ARRAY sem elemento reconhecido mostra 'UNKNOWN[]', não quebra."""
        coluna = construir_coluna(
            nome="pontos", tipo_dado=TipoDeDado(categoria=CategoriaDeDado.ARRAY)
        )
        tabela = construir_tabela(colunas=[coluna])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_colunas = next(
            linha for linha in secao_colunas.splitlines() if "pontos" in linha
        )
        assert "UNKNOWN[]" in linha_colunas

    def test_amostra_vazia_mostra_sem_evidencia_em_vez_de_completude_falsa(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """tamanho_amostra == 0 mostra 'sem evidência', não 100%/0.00% falsos.

        _metricas_vazias() zera percentual_nulo pra amostra vazia — sem essa
        distinção na apresentação, a tabela mostraria 100% de completude e
        0.00% de nulos/duplicatas como se a amostra tivesse confirmado isso,
        quando na real nenhuma linha foi inspecionada (issue #56).
        """
        metrica_vazia = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=0.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="email", metricas=[metrica_vazia])
        tabela = construir_tabela(
            colunas=[coluna],
            tamanho_amostra=0,
            metricas=[MetricasBaseTabela(completude=100.0)],
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        assert (
            "sem evidência (amostra vazia)" in conteudo.split("## Fatos extraídos")[1]
        )
        secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
        linha = next(
            linha
            for linha in secao_qualidade.splitlines()
            if linha.startswith("| email ")
        )
        assert "sem evidência (amostra vazia)" in linha
        assert "0.00%" not in linha

    def test_nivel_de_confianca_baixa_aparece_nos_fatos_extraidos(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """MetricasDeConfianca(nivel=BAIXA) renderiza o rótulo de cautela."""
        coluna = construir_coluna(nome="id", metricas=[metrica_coluna_completa])
        tabela = construir_tabela(
            colunas=[coluna],
            metricas=[
                MetricasBaseTabela(completude=100.0),
                MetricasDeConfianca(nivel=NivelDeConfianca.BAIXA),
            ],
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_fatos = conteudo.split("## Fatos extraídos")[1]
        assert "Confiança estatística:** baixa" in secao_fatos

    def test_confianca_ausente_mostra_nao_disponivel(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
        metrica_coluna_completa: MetricasBaseColuna,
    ) -> None:
        """Tabela sem MetricasDeConfianca calculada mostra 'N/D', não quebra."""
        coluna = construir_coluna(nome="id", metricas=[metrica_coluna_completa])
        tabela = construir_tabela(
            colunas=[coluna], metricas=[MetricasBaseTabela(completude=100.0)]
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_fatos = conteudo.split("## Fatos extraídos")[1]
        assert "Confiança estatística:** N/D" in secao_fatos

    def test_nao_nulavel_tem_precedencia_mesmo_com_amostra_vazia(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """NOT NULL do schema continua valendo mesmo sem evidência amostral.

        Garantia estrutural do catálogo não depende da amostra ter encontrado
        alguma linha — diferente de percentual_unico (célula seguinte), que não
        tem fato estrutural equivalente e por isso continua 'sem evidência'.
        """
        metrica_vazia = MetricasBaseColuna(
            percentual_nulo=0.0, percentual_unico=0.0, valores_frequentes=[]
        )
        coluna = construir_coluna(nome="id", nao_nulavel=True, metricas=[metrica_vazia])
        tabela = construir_tabela(colunas=[coluna], tamanho_amostra=0)
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_qualidade = conteudo.split("## Qualidade dos dados")[1]
        linha = next(
            linha for linha in secao_qualidade.splitlines() if linha.startswith("| id ")
        )
        _, _, percentual_nulo, percentual_unico, _minimo, _maximo, _formato, _ = (
            celula.strip() for celula in linha.split("|")
        )
        assert percentual_nulo == "0.00% (garantido pelo schema)"
        assert percentual_unico == "sem evidência (amostra vazia)"

    def test_restricoes_unicas_ausente_omite_bullet(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Tabela sem UNIQUE composto não mostra o bullet."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        assert "Restrições UNIQUE compostas" not in conteudo

    def test_coluna_pk_e_em_restricao_composta_nao_mostra_marcador_composto(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """PK que também participa de UNIQUE composto não duplica marcador."""
        coluna_pk = construir_coluna(nome="id", chave_primaria=True)
        tabela = construir_tabela(
            colunas=[coluna_pk],
            restricoes_unicas=[RestricaoUnica(colunas=("id", "versao"))],
        )
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        secao_colunas = conteudo.split("## Colunas")[1].split("## Qualidade")[0]
        linha_id = next(linha for linha in secao_colunas.splitlines() if "id" in linha)
        assert "PK" in linha_id
        assert "UNIQUE (composto)" not in linha_id

    def test_restricoes_fk_compostas_ausente_omite_bullet(
        self,
        tmp_path: Path,
        construir_coluna: Callable[..., ColunaAnalisada],
        construir_tabela: Callable[..., TabelaAnalisada],
        construir_banco: Callable[[list[TabelaAnalisada]], BancoAnalisado],
    ) -> None:
        """Tabela sem FK composta não mostra o bullet."""
        tabela = construir_tabela(colunas=[construir_coluna()])
        banco = construir_banco([tabela])

        resultado = GeradorMarkdown()(banco, tmp_path)

        assert isinstance(resultado, Sucesso)
        conteudo = (tmp_path / "escopo" / "tabela.md").read_text()
        assert "Chaves estrangeiras compostas" not in conteudo

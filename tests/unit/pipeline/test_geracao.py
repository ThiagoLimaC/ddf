"""Testes do núcleo de Port da etapa de geração (sem UI)."""

from dataclasses import dataclass, field
from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado, TipoDeMetrica
from ddf.domain.ports.gerador import Gerador
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Sucesso
from ddf.pipeline import geracao


@dataclass
class GeradorFake:
    """Gerador fake com resultado/exceção configuráveis, sem escrita real."""

    requer: list[TipoDeMetrica] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)
    falha: str | None = None
    excecao: Exception | None = None
    destino_recebido: Path | None = None

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Sucesso[None] | Falha:
        """Registra o destino recebido e devolve a resposta configurada."""
        self.destino_recebido = destino
        if self.excecao is not None:
            raise self.excecao
        if self.falha is not None:
            return Falha(erro=self.falha, avisos=self.avisos)
        return Sucesso(valor=None, avisos=self.avisos)


class TestFeliz:
    """Caminho feliz."""

    def test_executa_um_gerador_em_subpasta_slugificada(
        self, tmp_path: Path
    ) -> None:
        """Escreve na subpasta destino/<slug>, slugificando o nome do registro."""
        gerador = GeradorFake()
        registrados: dict[str, Gerador] = {"Markdown": gerador}

        resultados = geracao.executar_geradores(
            ["Markdown"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert len(resultados) == 1
        assert resultados[0].nome == "Markdown"
        assert resultados[0].destino == tmp_path / "markdown"
        assert resultados[0].resultado == Sucesso(valor=None)
        assert gerador.destino_recebido == tmp_path / "markdown"

    def test_executa_multiplos_geradores_na_ordem_recebida(
        self, tmp_path: Path
    ) -> None:
        """Preserva a ordem de nomes_geradores no resultado."""
        registrados: dict[str, Gerador] = {
            "Markdown": GeradorFake(),
            "Dbt": GeradorFake(),
        }

        resultados = geracao.executar_geradores(
            ["Dbt", "Markdown"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert [item.nome for item in resultados] == ["Dbt", "Markdown"]

    def test_progresso_e_chamado_uma_vez_por_gerador_apos_terminar(
        self, tmp_path: Path
    ) -> None:
        """Progresso recebe cada ResultadoDeGerador, na mesma ordem da execução."""
        registrados: dict[str, Gerador] = {
            "Markdown": GeradorFake(),
            "Dbt": GeradorFake(),
        }
        eventos: list[str] = []

        geracao.executar_geradores(
            ["Markdown", "Dbt"],
            registrados,
            BancoAnalisado(tabelas=[]),
            tmp_path,
            progresso=lambda item: eventos.append(item.nome),
        )

        assert eventos == ["Markdown", "Dbt"]


class TestErro:
    """Erro esperado."""

    def test_gerador_que_devolve_falha_nao_interrompe_os_demais(
        self, tmp_path: Path
    ) -> None:
        """Falha de 1 Gerador não impede a execução dos demais — sucesso parcial."""
        registrados: dict[str, Gerador] = {
            "Markdown": GeradorFake(falha="disco cheio"),
            "Dbt": GeradorFake(),
        }

        resultados = geracao.executar_geradores(
            ["Markdown", "Dbt"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert isinstance(resultados[0].resultado, Falha)
        assert resultados[0].resultado.erro == "disco cheio"
        assert isinstance(resultados[1].resultado, Sucesso)

    def test_gerador_que_levanta_excecao_vira_falha_via_rede_de_seguranca(
        self, tmp_path: Path
    ) -> None:
        """Exceção não prevista pelo Gerador é convertida em Falha, não propaga."""
        registrados: dict[str, Gerador] = {
            "Markdown": GeradorFake(excecao=ValueError("boom"))
        }

        resultados = geracao.executar_geradores(
            ["Markdown"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert isinstance(resultados[0].resultado, Falha)
        assert "Markdown" in resultados[0].resultado.erro


class TestBorda:
    """Bordas."""

    def test_lista_vazia_de_nomes_devolve_lista_vazia(self, tmp_path: Path) -> None:
        """Nenhum Gerador escolhido — não executa nada, não chama progresso."""
        chamadas: list[str] = []

        resultados = geracao.executar_geradores(
            [],
            {},
            BancoAnalisado(tabelas=[]),
            tmp_path,
            progresso=lambda item: chamadas.append(item.nome),
        )

        assert resultados == []
        assert chamadas == []

    def test_slugifica_sigla_e_camelcase_sem_excecao_cadastrada(
        self, tmp_path: Path
    ) -> None:
        """'ContextoDeIA' slugifica pra 'contexto_de_ia', sem dicionário fixo."""
        gerador = GeradorFake()
        registrados: dict[str, Gerador] = {"ContextoDeIA": gerador}

        resultados = geracao.executar_geradores(
            ["ContextoDeIA"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert resultados[0].destino == tmp_path / "contexto_de_ia"

    def test_avisos_do_gerador_chegam_intactos_no_resultado(
        self, tmp_path: Path
    ) -> None:
        """Avisos emitidos pelo Gerador não são descartados no repasse."""
        aviso = Aviso(mensagem="coluna sem descrição", origem="Markdown")
        registrados: dict[str, Gerador] = {"Markdown": GeradorFake(avisos=[aviso])}

        resultados = geracao.executar_geradores(
            ["Markdown"], registrados, BancoAnalisado(tabelas=[]), tmp_path
        )

        assert resultados[0].resultado.avisos == [aviso]

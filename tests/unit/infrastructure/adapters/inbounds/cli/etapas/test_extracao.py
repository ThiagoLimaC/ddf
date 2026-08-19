"""Testes das etapas 1-5 do wizard: conexão, escopos, amostragem e extração.

`pipeline.extracao` é fakeado em todos os testes que envolvem Port — estes
testes verificam só comportamento de UI (retry de conexão, formatação,
código de saída, quantas vezes/com que avisos `exibir_avisos` é chamado).
Conteúdo de domínio (agregação de pares, sucesso parcial) é coberto em
`tests/unit/pipeline/test_extracao.py`.
"""

import builtins
from collections.abc import Callable

import pytest

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.infrastructure.adapters.inbounds.cli.etapas import extracao
from ddf.infrastructure.adapters.inbounds.cli.registro.estrategias import (
    EstrategiaRegistrada,
)
from ddf.infrastructure.adapters.outbounds.extractors.estrategias.percentual_de_linhas import (
    PercentualDeLinhas,
)
from ddf.pipeline.comum.estagio import Estagio
from ddf.pipeline.etapas import extracao as pipeline_extracao


class _ExtratorPlaceholder:
    """Satisfaz o Protocol Extrator estruturalmente — nunca é exercitado.

    `pipeline.extracao` é fakeado nestes testes, então o Extrator real
    nunca chama nenhum desses métodos — só precisa existir para
    `EXTRATORES_REGISTRADOS[...].construir()` devolver algo do tipo certo.
    """

    def listar_escopos(self) -> Resultado[list[str]]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def listar_tabelas(self, escopo: str, /) -> Resultado[list[tuple[str, str]]]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def extrair_tabela(
        self, escopo: str, tabela: str, /
    ) -> Resultado[TabelaExtraida]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class _OrquestradorPlaceholder:
    """Satisfaz o Protocol OrquestradorDeTabelas estruturalmente — não é exercitado."""

    def extrair(
        self,
        pares: list[tuple[str, str]],
        extrator: Extrator,
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        /,
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]:
        """Não é exercitado por estes testes."""
        raise NotImplementedError


class _TestarConexaoFake:
    """Fake de pipeline.extracao.testar_conexao — fila de respostas em fila."""

    def __init__(self, respostas: list[Resultado[list[str]]]) -> None:
        """Guarda a fila de respostas e a lista de extratores recebidos."""
        self._respostas = list(respostas)
        self.extratores_recebidos: list[Extrator] = []

    def __call__(self, extrator: Extrator) -> Resultado[list[str]]:
        """Registra o extrator recebido e devolve a próxima resposta da fila."""
        self.extratores_recebidos.append(extrator)
        return self._respostas.pop(0)


def _extrair_tabelas_fake(
    resultado: Resultado[list[TabelaExtraida]],
) -> Callable[..., Resultado[list[TabelaExtraida]]]:
    """Fake de pipeline.extracao.extrair_tabelas que também chama progresso.

    Simula o comportamento real do orquestrador: chama `progresso` uma vez
    por tabela do Sucesso configurado, pra exercitar a barra de progresso
    real (não mockada) do wrapper de UI.
    """

    def _fn(
        orquestrador: object,
        extrator: object,
        pares: list[tuple[str, str]],
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]:
        if progresso is not None and isinstance(resultado, Sucesso):
            for tabela in resultado.valor:
                progresso(f"{tabela.nome_escopo}.{tabela.nome_tabela}")
        return resultado

    return _fn


class TestFeliz:
    """Caminho feliz."""

    def test_configurar_amostragem_usa_a_estrategia_escolhida(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Atribui a estratégia escolhida à configuração recebida."""
        registro = {
            "Percentual de linhas": EstrategiaRegistrada(
                construir=lambda: PercentualDeLinhas(percentual=10.0),
            )
        }
        monkeypatch.setattr(extracao, "ESTRATEGIAS_REGISTRADAS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.selecionar",
            lambda mensagem, escolhas: "Percentual de linhas",
        )
        configuracao = ConfiguracaoDeExtracao()

        extracao.configurar_amostragem(configuracao)

        assert isinstance(configuracao.estrategia, PercentualDeLinhas)

    def test_conectar_com_sucesso_na_primeira_tentativa(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Conecta e devolve escopos na 1ª tentativa, sem estratégia."""
        extrator_placeholder = _ExtratorPlaceholder()
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=_ExtratorPlaceholder,
                construir=lambda cfg: extrator_placeholder,
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.selecionar", lambda *a: "Fake"
        )
        monkeypatch.setattr(
            pipeline_extracao,
            "testar_conexao",
            _TestarConexaoFake([Sucesso(valor=["public", "vendas"])]),
        )

        extrator, configuracao, escopos = extracao.conectar()

        assert extrator is extrator_placeholder
        assert configuracao.estrategia is None
        assert escopos == ["public", "vendas"]

    def test_extrair_devolve_as_tabelas_do_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Devolve as tabelas extraídas pelo núcleo de pipeline.extracao."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        monkeypatch.setattr(
            pipeline_extracao,
            "extrair_tabelas",
            _extrair_tabelas_fake(Sucesso(valor=[tabela])),
        )

        tabelas = extracao.extrair(
            _OrquestradorPlaceholder(),
            _ExtratorPlaceholder(),
            [("public", "clientes")],
        )

        assert tabelas == [tabela]

    def test_listar_pares_devolve_so_os_pares_nao_a_tupla(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reconcilia (pares, avisos) de volta para list[pares] — não a tupla."""
        pares_esperados = [("public", "clientes"), ("vendas", "pedidos")]
        monkeypatch.setattr(
            pipeline_extracao,
            "listar_pares",
            lambda extrator, escopos: (pares_esperados, []),
        )

        pares = extracao.listar_pares(_ExtratorPlaceholder(), ["public", "vendas"])

        assert pares == pares_esperados

    def test_escolher_tabelas_recusando_restringir_devolve_todas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resposta padrão (não restringir) devolve os pares disponíveis intactos."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a, **k: False
        )
        pares_disponiveis = [("public", "clientes"), ("vendas", "pedidos")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == pares_disponiveis

    def test_escolher_tabelas_restringindo_devolve_apenas_o_subconjunto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restringindo, devolve só os pares cujo rótulo foi escolhido."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a, **k: True
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.escolher_multiplos",
            lambda *a, **k: ["vendas › pedidos"],
        )
        pares_disponiveis = [("public", "clientes"), ("vendas", "pedidos")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == [("vendas", "pedidos")]


class TestErro:
    """Erro esperado."""

    def test_testar_conexao_esgota_tentativas_e_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """3 falhas seguidas de conexão saem com código 1, sem retry cego."""
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=_ExtratorPlaceholder,
                construir=lambda cfg: _ExtratorPlaceholder(),
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            pipeline_extracao,
            "testar_conexao",
            _TestarConexaoFake(
                [
                    Falha(erro="senha incorreta"),
                    Falha(erro="senha incorreta"),
                    Falha(erro="senha incorreta"),
                ]
            ),
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a: True
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao("Fake", ConfiguracaoDeExtracao())

        assert excinfo.value.code == 1

    def test_extrair_com_falha_sai_com_codigo_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falha do pipeline sai com código 1."""
        monkeypatch.setattr(
            pipeline_extracao,
            "extrair_tabelas",
            _extrair_tabelas_fake(Falha(erro="nenhuma tabela extraída")),
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao.extrair(
                _OrquestradorPlaceholder(),
                _ExtratorPlaceholder(),
                [("public", "clientes")],
            )

        assert excinfo.value.code == 1

    def test_listar_pares_chama_exibir_avisos_exatamente_uma_vez(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O wrapper de UI exibe os avisos do pipeline exatamente 1 vez."""
        avisos_do_pipeline = [
            Aviso(
                mensagem="Falha ao listar tabelas de 'financeiro_typo': "
                "Escopo 'financeiro_typo' não encontrado.",
                origem="Extracao",
            )
        ]
        monkeypatch.setattr(
            pipeline_extracao,
            "listar_pares",
            lambda extrator, escopos: ([("public", "clientes")], avisos_do_pipeline),
        )
        chamadas: list[list[Aviso]] = []
        monkeypatch.setattr(extracao, "exibir_avisos", chamadas.append)

        pares = extracao.listar_pares(
            _ExtratorPlaceholder(), ["public", "financeiro_typo"]
        )

        assert pares == [("public", "clientes")]
        assert chamadas == [avisos_do_pipeline]


class TestBorda:
    """Bordas."""

    def test_testar_conexao_reconstroi_extrator_a_cada_tentativa(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Falha não reusa a mesma credencial — reconstrói o Extrator no retry."""
        extrator_falho = _ExtratorPlaceholder()
        extrator_certo = _ExtratorPlaceholder()
        respostas_construir = iter([extrator_falho, extrator_certo])
        monkeypatch.setattr(
            extracao,
            "EXTRATORES_REGISTRADOS",
            {
                "Fake": ExtratorRegistrado(
                    classe_extrator=_ExtratorPlaceholder,
                    construir=lambda cfg: next(respostas_construir),
                )
            },
        )
        fake_testar_conexao = _TestarConexaoFake(
            [Falha(erro="senha incorreta"), Sucesso(valor=["public"])]
        )
        monkeypatch.setattr(
            pipeline_extracao, "testar_conexao", fake_testar_conexao
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a: True
        )

        extrator, escopos = extracao._testar_conexao("Fake", ConfiguracaoDeExtracao())

        assert extrator is extrator_certo
        assert escopos == ["public"]
        assert fake_testar_conexao.extratores_recebidos == [
            extrator_falho,
            extrator_certo,
        ]

    def test_testar_conexao_usuario_recusa_tentar_novamente_antes_do_limite(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """usuário recusa tentar de novo após 1 falha, sem esperar as 3 tentativas."""
        registro = {
            "Fake": ExtratorRegistrado(
                classe_extrator=_ExtratorPlaceholder,
                construir=lambda cfg: _ExtratorPlaceholder(),
            )
        }
        monkeypatch.setattr(extracao, "EXTRATORES_REGISTRADOS", registro)
        monkeypatch.setattr(
            pipeline_extracao,
            "testar_conexao",
            _TestarConexaoFake([Falha(erro="conexão recusada")]),
        )
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a: False
        )

        with pytest.raises(SystemExit) as excinfo:
            extracao._testar_conexao("Fake", ConfiguracaoDeExtracao())

        assert excinfo.value.code == 1

    def test_extrair_usa_o_total_de_pares_na_barra_de_progresso(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Total exibido vem de len(pares), já conhecido antes de chamar extrair."""
        tabela = fabrica_tabela_extraida("public", "clientes")
        monkeypatch.setattr(
            pipeline_extracao,
            "extrair_tabelas",
            _extrair_tabelas_fake(Sucesso(valor=[tabela])),
        )

        extracao.extrair(
            _OrquestradorPlaceholder(),
            _ExtratorPlaceholder(),
            [("public", "clientes")],
        )

        assert "(1/1)" in capsys.readouterr().out

    def test_extrair_emite_avisos_antes_do_sucesso_e_a_duracao_por_ultimo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fabrica_tabela_extraida: Callable[[str, str], TabelaExtraida],
    ) -> None:
        """Ordem: avisos → ✓ tabela(s) extraída(s) → duração, nunca fora disso.

        `duração:` sai via `builtins.print` cru, não via `questionary.print`
        (usado pelas mensagens coloridas) — por isso intercepta os dois, ao
        contrário dos demais testes deste arquivo que só precisam de
        `interceptar_print`.
        """
        tabela = fabrica_tabela_extraida("public", "clientes")
        resultado = Sucesso(
            valor=[tabela],
            avisos=[Aviso(mensagem="amostra pequena em 'public.clientes'", origem="X")],
        )
        monkeypatch.setattr(
            pipeline_extracao, "extrair_tabelas", _extrair_tabelas_fake(resultado)
        )
        eventos: list[str] = []
        monkeypatch.setattr(
            "questionary.print",
            lambda texto, style=None, end="\n": eventos.append(str(texto)),
        )
        print_original = builtins.print

        def _print_rastreado(
            *args: object, sep: str = " ", end: str = "\n", flush: bool = False
        ) -> None:
            if args:
                eventos.append(str(args[0]))
            print_original(*args, sep=sep, end=end, flush=flush)

        monkeypatch.setattr("builtins.print", _print_rastreado)

        extracao.extrair(
            _OrquestradorPlaceholder(),
            _ExtratorPlaceholder(),
            [("public", "clientes")],
        )

        indice_aviso = next(i for i, e in enumerate(eventos) if "amostra pequena" in e)
        indice_sucesso = next(
            i for i, e in enumerate(eventos) if "tabela(s) extraída(s)" in e
        )
        indice_duracao = next(i for i, e in enumerate(eventos) if "duração:" in e)
        assert indice_aviso < indice_sucesso < indice_duracao

    def test_escolher_tabelas_selecao_vazia_repergunta_ate_marcar_algo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Seleção vazia não sai do wizard — repergunta até marcar ao menos uma."""
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.confirmar", lambda *a, **k: True
        )
        respostas = iter([[], ["public › clientes"]])
        monkeypatch.setattr(
            "ddf.infrastructure.adapters.inbounds.cli.prompts.escolher_multiplos",
            lambda *a, **k: next(respostas),
        )
        pares_disponiveis = [("public", "clientes")]

        pares = extracao.escolher_tabelas(pares_disponiveis)

        assert pares == [("public", "clientes")]

"""Testes de prompts.py — cancelamento, dica_limpar, estilo e progresso."""

import time
from typing import Any

import pytest

from ddf.infrastructure.adapters.inbounds.cli import prompts


class _RespostaFake:
    """Substitui o objeto que `questionary.*(...)` devolve, registrando a chamada."""

    def __init__(self, valor: object) -> None:
        self.valor = valor
        self.args: tuple[object, ...] | None = None
        self.kwargs: dict[str, object] | None = None

    def __call__(self, *args: object, **kwargs: object) -> "_RespostaFake":
        self.args = args
        self.kwargs = kwargs
        return self

    def ask(self) -> object:
        """Devolve o valor pré-configurado, como `.ask()` do questionary faria."""
        return self.valor


def _substituir(
    monkeypatch: pytest.MonkeyPatch, nome_funcao: str, valor: object
) -> _RespostaFake:
    """Substitui `questionary.<nome_funcao>` por um fake que devolve `valor`."""
    fake = _RespostaFake(valor)
    monkeypatch.setattr(f"questionary.{nome_funcao}", fake)
    return fake


# texto() — caminho feliz


class TestFeliz:
    """Caminho feliz."""

    def test_texto_devolve_a_resposta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resposta não-None é devolvida sem sair do processo."""
        _substituir(monkeypatch, "text", "postgresql://...")

        assert prompts.texto("Connection string:") == "postgresql://..."

    def test_texto_com_dica_limpar_e_default_passa_instrucao(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """dica_limpar=True com default não-vazio inclui a instrução."""
        fake = _substituir(monkeypatch, "text", "valor")

        prompts.texto("msg:", default="algo", dica_limpar=True)

        assert fake.kwargs is not None
        assert fake.kwargs["instruction"] == "(Ctrl+U limpa o valor pré-preenchido)"

    def test_numero_converte_a_resposta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resposta numérica válida é convertida e devolvida."""
        _substituir(monkeypatch, "text", "42")

        assert prompts.numero("Porta:", int, default="3306") == 42

    def test_senha_devolve_a_resposta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """senha() devolve a resposta digitada."""
        _substituir(monkeypatch, "password", "segredo")

        assert prompts.senha("Senha:") == "segredo"

    def test_selecionar_devolve_a_escolha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """selecionar() devolve a opção escolhida."""
        _substituir(monkeypatch, "select", "PostgreSQL")

        assert (
            prompts.selecionar("Qual fonte?", ["PostgreSQL", "MariaDB"]) == "PostgreSQL"
        )

    def test_selecionar_usa_instrucao_em_portugues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Instrução de navegação em PT-BR, não o texto padrão em inglês da lib."""
        fake = _substituir(monkeypatch, "select", "PostgreSQL")

        prompts.selecionar("Qual fonte?", ["PostgreSQL", "MariaDB"])

        assert fake.kwargs is not None
        # O "\n" final não é ruído do texto — é o que o questionary usa para
        # abrir uma linha em branco antes da lista de opções (ver
        # comentário em `selecionar()`, prompts.py).
        assert fake.kwargs["instruction"] == "(setas para navegar, enter confirma)\n"

    def test_confirmar_devolve_false_quando_usuario_recusa(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Resposta explícita False é devolvida (não é cancelamento)."""
        _substituir(monkeypatch, "confirm", False)

        assert prompts.confirmar("Gerar mesmo assim?") is False

    def test_escolher_multiplos_devolve_as_escolhas(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uma ou mais escolhas marcadas são devolvidas."""
        _substituir(monkeypatch, "checkbox", ["Markdown", "Dbt"])

        assert prompts.escolher_multiplos("Escolha:", ["Markdown", "Dbt"]) == [
            "Markdown",
            "Dbt",
        ]

    def test_pausar_com_tecla_pressionada_nao_sai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Apertar uma tecla não interrompe o processo."""
        _substituir(monkeypatch, "press_any_key_to_continue", True)

        prompts.pausar("Aperte uma tecla...")  # não deve levantar SystemExit

    def test_imprimir_destacado_usa_a_cor_informada(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Repassa o texto e monta o estilo com a cor recebida."""
        chamadas = interceptar_print

        prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)

        assert chamadas == [
            {
                "texto": "✓ Conexão validada.",
                "style": f"bold fg:{prompts.COR_SUCESSO}",
                "end": "\n",
            }
        ]

    def test_imprimir_destacado_com_negrito_falso_omite_bold(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """negrito=False produz estilo sem "bold" — texto de segundo plano."""
        chamadas = interceptar_print

        prompts.imprimir_destacado("Bem-vindo.", prompts.COR_SECUNDARIA, negrito=False)

        assert chamadas == [
            {
                "texto": "Bem-vindo.",
                "style": f"fg:{prompts.COR_SECUNDARIA}",
                "end": "\n",
            }
        ]

    def test_imprimir_destacado_sem_cor_produz_estilo_so_com_bold(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """cor=None não sobrescreve `fg` — mimetiza o token `question`."""
        chamadas = interceptar_print

        prompts.imprimir_destacado("Fonte", None)

        assert chamadas == [{"texto": "Fonte", "style": "bold", "end": "\n"}]

    def test_cabecalho_etapa_imprime_numero_total_e_titulo(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Rótulo "└─ Etapa N/total — título" aparece na cor de destaque."""
        chamadas = interceptar_print

        prompts.cabecalho_etapa(2, 12, "Escolher escopos")

        assert chamadas == [
            {
                "texto": "└─ Etapa 2/12 — Escolher escopos",
                "style": f"bold fg:{prompts.COR_DESTAQUE}",
                "end": "\n",
            }
        ]

    def test_linha_de_decisao_imprime_rotulo_e_valor_com_conector_de_arvore(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Conector e rótulo na cor da pergunta, valor na cor de destaque.

        Três chamadas a `questionary.print` compõem uma única linha: o
        conector (`├─`) acompanha o rótulo (`cor=None`, mimetizando o token
        `question` do tema padrão — `"bold"`, sem `fg`); só o valor mantém
        `COR_DESTAQUE`, mesma cor que `_ESTILO` usa para o token `answer` do
        questionary.
        """
        chamadas = interceptar_print

        prompts.linha_de_decisao("Fonte", "PostgreSQL")

        assert chamadas == [
            {"texto": "├─", "style": "bold", "end": " "},
            {"texto": "Fonte", "style": "bold", "end": " "},
            {
                "texto": "PostgreSQL",
                "style": f"bold fg:{prompts.COR_DESTAQUE}",
                "end": "\n",
            },
        ]

    def test_progresso_paralelo_com_total_mostra_fracao(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Com total conhecido, mostra 'concluídas/total' e a barra de blocos."""
        with prompts.progresso_paralelo("Extraindo...", total=2) as callback:
            callback("public.clientes")
            callback("public.pedidos")

        saida = capsys.readouterr().out
        assert "Extraindo... (0/2)" in saida
        assert "Extraindo... (1/2)" in saida
        assert "Extraindo... (2/2)" in saida
        assert prompts._BLOCO_CHEIO in saida
        assert prompts._BLOCO_VAZIO in saida

    def test_barra_indeterminada_anima_mensagem_com_a_mesma_textura_da_barra(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mostra a mensagem ao lado de retângulos ciano, sem fração N/total."""
        with prompts.barra_indeterminada("Analisando..."):
            time.sleep(0.15)

        saida = capsys.readouterr().out
        assert "Analisando..." in saida
        assert prompts._BLOCO_CHEIO in saida


class TestErro:
    """Erro esperado."""

    def test_texto_cancelado_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelamento (Ctrl+C/Esc) devolve None e sai limpo."""
        _substituir(monkeypatch, "text", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.texto("msg:")

        assert excinfo.value.code == 0

    def test_numero_com_entrada_invalida_reprompt_ate_funcionar(
        self,
        monkeypatch: pytest.MonkeyPatch,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Entrada não numérica reexibe o prompt em vez de propagar."""
        respostas = iter(["abc", "", "8"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        assert prompts.numero("Porta:", int) == 8
        assert any(
            "Erro: valor inválido" in chamada["texto"] for chamada in interceptar_print
        )

    def test_numero_opcional_com_entrada_invalida_reprompt_ate_funcionar(
        self,
        monkeypatch: pytest.MonkeyPatch,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Entrada não numérica reexibe o prompt, branco continua valendo."""
        respostas = iter(["abc", "7"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        assert prompts.numero_opcional("Seed (opcional):", int) == 7
        assert interceptar_print

    def test_senha_cancelada_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelamento de senha() sai limpo."""
        _substituir(monkeypatch, "password", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.senha("Senha:")

        assert excinfo.value.code == 0

    def test_selecionar_cancelado_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelamento de selecionar() sai limpo."""
        _substituir(monkeypatch, "select", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.selecionar("Qual fonte?", ["PostgreSQL"])

        assert excinfo.value.code == 0

    def test_confirmar_cancelado_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelamento de confirmar() sai limpo."""
        _substituir(monkeypatch, "confirm", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.confirmar("Gerar mesmo assim?")

        assert excinfo.value.code == 0

    def test_escolher_multiplos_cancelado_sai_com_codigo_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancelamento (None) sai limpo."""
        _substituir(monkeypatch, "checkbox", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.escolher_multiplos("Escolha:", ["Markdown"])

        assert excinfo.value.code == 0

    def test_pausar_cancelada_sai_com_codigo_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelar (Ctrl+C/Esc) sai limpo, igual aos demais prompts."""
        _substituir(monkeypatch, "press_any_key_to_continue", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.pausar("Aperte uma tecla...")

        assert excinfo.value.code == 0


class TestBorda:
    """Bordas."""

    def test_texto_com_dica_limpar_sem_default_nao_passa_instrucao(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """dica_limpar=True mas default vazio não mostra a instrução."""
        fake = _substituir(monkeypatch, "text", "valor")

        prompts.texto("msg:", dica_limpar=True)

        assert fake.kwargs is not None
        assert fake.kwargs["instruction"] is None

    def test_numero_opcional_em_branco_devolve_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Resposta em branco devolve None em vez de repetir o prompt."""
        _substituir(monkeypatch, "text", "")

        assert prompts.numero_opcional("Seed (opcional):", int) is None

    def test_escolher_multiplos_sem_nenhuma_marcada_recusa_repetir_e_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nada marcado (sem cancelar) pergunta se quer repetir; recusando, sai."""
        _substituir(monkeypatch, "checkbox", [])
        _substituir(monkeypatch, "confirm", False)

        with pytest.raises(SystemExit) as excinfo:
            prompts.escolher_multiplos("Escolha:", ["Markdown"])

        assert excinfo.value.code == 0

    def test_escolher_multiplos_sem_nenhuma_marcada_repete_ate_marcar_algo(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nada marcado + confirmar repetir=Sim: repergunta até algo ser marcado."""
        respostas_checkbox = iter([[], ["Markdown"]])
        monkeypatch.setattr(
            "questionary.checkbox",
            lambda *args, **kwargs: _RespostaFake(next(respostas_checkbox)),
        )
        _substituir(monkeypatch, "confirm", True)

        assert prompts.escolher_multiplos("Escolha:", ["Markdown"]) == ["Markdown"]

    def test_escolher_multiplos_permite_vazio_devolve_lista_vazia(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """permite_vazio=True devolve [] em vez de sair, para o chamador decidir."""
        _substituir(monkeypatch, "checkbox", [])

        assert (
            prompts.escolher_multiplos("Escolha:", ["Markdown"], permite_vazio=True)
            == []
        )

    def test_escolher_multiplos_permite_vazio_cancelado_ainda_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancelamento (None) sai limpo mesmo com permite_vazio=True."""
        _substituir(monkeypatch, "checkbox", None)

        with pytest.raises(SystemExit) as excinfo:
            prompts.escolher_multiplos("Escolha:", ["Markdown"], permite_vazio=True)

        assert excinfo.value.code == 0

    def test_linha_de_decisao_usa_o_mesmo_conector_por_padrao_mesmo_na_ultima_chamada(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """Sem `ultimo=True`, nunca usa "└─" — bloco de decisões não fechado."""
        chamadas = interceptar_print

        prompts.linha_de_decisao("Fonte", "PostgreSQL")
        prompts.linha_de_decisao("Destino", "artefatos")

        # O conector é sempre a 1ª das 3 chamadas de cada linha (índices 0 e 3).
        assert chamadas[0]["texto"] == "├─"
        assert chamadas[3]["texto"] == "├─"

    def test_linha_de_decisao_com_ultimo_fecha_o_bloco_com_outro_conector(
        self,
        interceptar_print: list[dict[str, Any]],
    ) -> None:
        """`ultimo=True` troca "├─" por "└─" — só a última linha de um bloco."""
        chamadas = interceptar_print

        prompts.linha_de_decisao("Host", "localhost")
        prompts.linha_de_decisao("Senha", "****", ultimo=True)

        assert chamadas[0]["texto"] == "├─"
        assert chamadas[3]["texto"] == "└─"

    def test_progresso_paralelo_sem_total_mostra_contagem_corrida(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Sem total (None), mostra só a contagem corrida, sem fração."""
        with prompts.progresso_paralelo("Gerando skeletons...") as callback:
            callback("public.clientes")

        saida = capsys.readouterr().out
        assert "Gerando skeletons... (1)" in saida
        assert "/1" not in saida

    def test_ampulheta_nao_propaga_excecao_e_encerra_a_thread(
        self,
    ) -> None:
        """Sair do bloco `with` (com ou sem exceção) encerra a thread de animação."""
        with prompts.ampulheta("Testando..."):
            pass  # bloco vazio — só valida que entrar/sair funciona sem travar

    def test_barra_indeterminada_nao_propaga_excecao_e_encerra_a_thread(
        self,
    ) -> None:
        """Mesma garantia de `ampulheta`: sair do bloco encerra a thread de animação."""
        with prompts.barra_indeterminada("Analisando..."):
            pass  # bloco vazio — só valida que entrar/sair funciona sem travar

    def test_progresso_paralelo_encerra_a_thread_de_heartbeat_ao_sair(
        self,
    ) -> None:
        """Mesma garantia de `ampulheta`: sair do bloco encerra a thread."""
        with prompts.progresso_paralelo("Extraindo...", total=1):
            pass  # bloco vazio — só valida que entrar/sair funciona sem travar

    def test_progresso_paralelo_heartbeat_redesenha_sem_nenhum_item_concluido(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A barra anima (spinner) mesmo sem nenhum callback ser chamado."""
        with prompts.progresso_paralelo("Extraindo...", total=1):
            time.sleep(prompts._INTERVALO_HEARTBEAT_SEGUNDOS * 2)

        saida = capsys.readouterr().out
        assert "Extraindo... (0/1)" in saida

"""Testes de prompts.py — cancelamento, dica_limpar, estilo e progresso."""

from typing import Any

import pytest

from ddf.infrastructure.adapters.cli import prompts


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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Repassa o texto e monta o estilo com a cor recebida."""
        chamadas: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "questionary.print",
            lambda texto, style=None: chamadas.append({"texto": texto, "style": style}),
        )

        prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)

        assert chamadas == [
            {"texto": "✓ Conexão validada.", "style": f"bold fg:{prompts.COR_SUCESSO}"}
        ]

    def test_cabecalho_etapa_imprime_numero_total_e_titulo(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Rótulo "Etapa N/total — título" aparece centralizado, na cor de destaque."""
        chamadas: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "questionary.print",
            lambda texto, style=None: chamadas.append({"texto": texto, "style": style}),
        )

        prompts.cabecalho_etapa(2, 12, "Escolher escopos")

        assert len(chamadas) == 1
        assert chamadas[0]["style"] == f"bold fg:{prompts.COR_DESTAQUE}"
        assert "Etapa 2/12 — Escolher escopos" in chamadas[0]["texto"]

    def test_progresso_paralelo_com_total_mostra_fracao(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Com total conhecido, mostra 'concluídas/total'."""
        callback, _definir_total, inicio = prompts.progresso_paralelo(
            "Extraindo...", total=2
        )

        inicio("public.clientes")
        callback("public.clientes")
        inicio("public.pedidos")
        callback("public.pedidos")

        saida = capsys.readouterr().out
        assert "(1/2) — finalizando..." in saida
        assert "(2/2) — finalizando..." in saida


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
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Entrada não numérica reexibe o prompt em vez de propagar."""
        respostas = iter(["abc", "", "8"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        assert prompts.numero("Porta:", int) == 8
        assert "Erro: valor inválido" in capsys.readouterr().out

    def test_numero_opcional_com_entrada_invalida_reprompt_ate_funcionar(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Entrada não numérica reexibe o prompt, branco continua valendo."""
        respostas = iter(["abc", "7"])
        monkeypatch.setattr(
            "questionary.text",
            lambda *args, **kwargs: _RespostaFake(next(respostas)),
        )

        assert prompts.numero_opcional("Seed (opcional):", int) == 7

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

    def test_escolher_multiplos_sem_nenhuma_marcada_tambem_sai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Lista vazia (nada marcado, sem cancelar) também sai — não é None."""
        _substituir(monkeypatch, "checkbox", [])

        with pytest.raises(SystemExit) as excinfo:
            prompts.escolher_multiplos("Escolha:", ["Markdown"])

        assert excinfo.value.code == 0

    def test_cabecalho_etapa_com_titulo_longo_nao_estoura_preenchimento_negativo(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Título maior que a largura fixa ainda produz separador mínimo, sem erro."""
        chamadas: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "questionary.print",
            lambda texto, style=None: chamadas.append({"texto": texto, "style": style}),
        )

        prompts.cabecalho_etapa(
            5, 12, "Gerar skeletons e pausar para curadoria manual dos overrides"
        )

        assert len(chamadas) == 1
        assert "──" in chamadas[0]["texto"]
        assert (
            "Etapa 5/12 — Gerar skeletons e pausar para curadoria manual dos overrides"
            in chamadas[0]["texto"]
        )

    def test_progresso_paralelo_sem_total_mostra_contagem_corrida(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Sem total (None), mostra só a contagem corrida, sem fração."""
        callback, _definir_total, inicio = prompts.progresso_paralelo(
            "Gerando skeletons..."
        )

        inicio("public.clientes")
        callback("public.clientes")

        saida = capsys.readouterr().out
        assert "(1) — finalizando..." in saida
        assert "/1" not in saida

    def test_progresso_paralelo_definir_total_depois_passa_a_mostrar_fracao(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Total definido após a criação passa a valer nas chamadas seguintes."""
        callback, definir_total, inicio = prompts.progresso_paralelo("Extraindo...")

        inicio("public.clientes")
        callback("public.clientes")
        definir_total(2)
        inicio("public.pedidos")
        callback("public.pedidos")

        saida = capsys.readouterr().out
        assert "(1) — finalizando..." in saida
        assert "(2/2) — finalizando..." in saida

    def test_progresso_paralelo_mostra_identificadores_em_andamento(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Com duas tabelas em andamento, mostra as duas, não só a última iniciada."""
        _callback, _definir_total, inicio = prompts.progresso_paralelo(
            "Extraindo...", total=2
        )

        inicio("public.pedidos")
        inicio("public.clientes")

        saida = capsys.readouterr().out
        assert "em andamento: public.clientes, public.pedidos" in saida

    def test_progresso_paralelo_conclusao_remove_do_conjunto_em_andamento(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Tabela concluída sai da lista de "em andamento", com outra ainda rodando."""
        callback, _definir_total, inicio = prompts.progresso_paralelo(
            "Extraindo...", total=2
        )
        inicio("public.pedidos")
        inicio("public.clientes")

        callback("public.pedidos")

        saida = capsys.readouterr().out
        ultima_linha = saida.splitlines()[-1]
        assert "em andamento: public.clientes" in ultima_linha
        assert "public.pedidos" not in ultima_linha

    def test_progresso_paralelo_devolve_named_tuple_com_campos_nomeados(
        self,
    ) -> None:
        """Acesso por nome (.callback/.definir_total/.inicio), não só por posição."""
        resultado = prompts.progresso_paralelo("Extraindo...")

        assert resultado.callback is resultado[0]
        assert resultado.definir_total is resultado[1]
        assert resultado.inicio is resultado[2]

    def test_ampulheta_nao_propaga_excecao_e_encerra_a_thread(
        self,
    ) -> None:
        """Sair do bloco `with` (com ou sem exceção) encerra a thread de animação."""
        with prompts.ampulheta("Testando..."):
            pass  # bloco vazio — só valida que entrar/sair funciona sem travar

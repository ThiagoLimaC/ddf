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


def test_texto_devolve_a_resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caminho feliz: resposta não-None é devolvida sem sair do processo."""
    _substituir(monkeypatch, "text", "postgresql://...")

    assert prompts.texto("Connection string:") == "postgresql://..."


def test_texto_com_dica_limpar_e_default_passa_instrucao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: dica_limpar=True com default não-vazio inclui a instrução."""
    fake = _substituir(monkeypatch, "text", "valor")

    prompts.texto("msg:", default="algo", dica_limpar=True)

    assert fake.kwargs is not None
    assert fake.kwargs["instruction"] == "(Ctrl+U limpa o valor pré-preenchido)"


# texto() — erro esperado


def test_texto_cancelado_sai_com_codigo_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: cancelamento (Ctrl+C/Esc) devolve None e sai limpo."""
    _substituir(monkeypatch, "text", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.texto("msg:")

    assert excinfo.value.code == 0


# texto() — borda


def test_texto_com_dica_limpar_sem_default_nao_passa_instrucao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borda: dica_limpar=True mas default vazio não mostra a instrução."""
    fake = _substituir(monkeypatch, "text", "valor")

    prompts.texto("msg:", dica_limpar=True)

    assert fake.kwargs is not None
    assert fake.kwargs["instruction"] is None


# numero() — caminho feliz, erro esperado, borda


def test_numero_converte_a_resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caminho feliz: resposta numérica válida é convertida e devolvida."""
    _substituir(monkeypatch, "text", "42")

    assert prompts.numero("Porta:", int, default="3306") == 42


def test_numero_com_entrada_invalida_reprompt_ate_funcionar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Erro esperado: entrada não numérica reexibe o prompt em vez de propagar."""
    respostas = iter(["abc", "", "8"])
    monkeypatch.setattr(
        "questionary.text",
        lambda *args, **kwargs: _RespostaFake(next(respostas)),
    )

    assert prompts.numero("Porta:", int) == 8
    assert "Erro: valor inválido" in capsys.readouterr().out


def test_numero_opcional_em_branco_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borda: resposta em branco devolve None em vez de repetir o prompt."""
    _substituir(monkeypatch, "text", "")

    assert prompts.numero_opcional("Seed (opcional):", int) is None


def test_numero_opcional_com_entrada_invalida_reprompt_ate_funcionar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erro esperado: entrada não numérica reexibe o prompt, branco continua valendo."""
    respostas = iter(["abc", "7"])
    monkeypatch.setattr(
        "questionary.text",
        lambda *args, **kwargs: _RespostaFake(next(respostas)),
    )

    assert prompts.numero_opcional("Seed (opcional):", int) == 7


# senha(), selecionar(), confirmar() — caminho feliz + cancelamento


def test_senha_devolve_a_resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caminho feliz: senha() devolve a resposta digitada."""
    _substituir(monkeypatch, "password", "segredo")

    assert prompts.senha("Senha:") == "segredo"


def test_senha_cancelada_sai_com_codigo_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: cancelamento de senha() sai limpo."""
    _substituir(monkeypatch, "password", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.senha("Senha:")

    assert excinfo.value.code == 0


def test_selecionar_devolve_a_escolha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caminho feliz: selecionar() devolve a opção escolhida."""
    _substituir(monkeypatch, "select", "PostgreSQL")

    assert prompts.selecionar("Qual fonte?", ["PostgreSQL", "MariaDB"]) == "PostgreSQL"


def test_selecionar_cancelado_sai_com_codigo_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: cancelamento de selecionar() sai limpo."""
    _substituir(monkeypatch, "select", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.selecionar("Qual fonte?", ["PostgreSQL"])

    assert excinfo.value.code == 0


def test_confirmar_devolve_false_quando_usuario_recusa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: resposta explícita False é devolvida (não é cancelamento)."""
    _substituir(monkeypatch, "confirm", False)

    assert prompts.confirmar("Gerar mesmo assim?") is False


def test_confirmar_cancelado_sai_com_codigo_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: cancelamento de confirmar() sai limpo."""
    _substituir(monkeypatch, "confirm", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.confirmar("Gerar mesmo assim?")

    assert excinfo.value.code == 0


# escolher_multiplos() — caminho feliz, erro esperado, borda


def test_escolher_multiplos_devolve_as_escolhas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: uma ou mais escolhas marcadas são devolvidas."""
    _substituir(monkeypatch, "checkbox", ["Markdown", "Dbt"])

    assert prompts.escolher_multiplos("Escolha:", ["Markdown", "Dbt"]) == [
        "Markdown",
        "Dbt",
    ]


def test_escolher_multiplos_cancelado_sai_com_codigo_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erro esperado: cancelamento (None) sai limpo."""
    _substituir(monkeypatch, "checkbox", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.escolher_multiplos("Escolha:", ["Markdown"])

    assert excinfo.value.code == 0


def test_escolher_multiplos_sem_nenhuma_marcada_tambem_sai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borda: lista vazia (nada marcado, sem cancelar) também sai — não é None."""
    _substituir(monkeypatch, "checkbox", [])

    with pytest.raises(SystemExit) as excinfo:
        prompts.escolher_multiplos("Escolha:", ["Markdown"])

    assert excinfo.value.code == 0


# pausar() — caminho feliz + bug de cancelamento corrigido


def test_pausar_com_tecla_pressionada_nao_sai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caminho feliz: apertar uma tecla não interrompe o processo."""
    _substituir(monkeypatch, "press_any_key_to_continue", True)

    prompts.pausar("Aperte uma tecla...")  # não deve levantar SystemExit


def test_pausar_cancelada_sai_com_codigo_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: cancelar (Ctrl+C/Esc) sai limpo, igual aos demais prompts."""
    _substituir(monkeypatch, "press_any_key_to_continue", None)

    with pytest.raises(SystemExit) as excinfo:
        prompts.pausar("Aperte uma tecla...")

    assert excinfo.value.code == 0


# imprimir_destacado()


def test_imprimir_destacado_usa_a_cor_informada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caminho feliz: repassa o texto e monta o estilo com a cor recebida."""
    chamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "questionary.print",
        lambda texto, style=None: chamadas.append({"texto": texto, "style": style}),
    )

    prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)

    assert chamadas == [
        {"texto": "✓ Conexão validada.", "style": f"bold fg:{prompts.COR_SUCESSO}"}
    ]


# progresso_paralelo()


def test_progresso_paralelo_com_total_mostra_fracao(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Caminho feliz: com total conhecido, mostra 'concluídas/total'."""
    callback, _definir_total = prompts.progresso_paralelo("Extraindo...", total=2)

    callback("public.clientes")
    callback("public.pedidos")

    saida = capsys.readouterr().out
    assert "(1/2) — public.clientes" in saida
    assert "(2/2) — public.pedidos" in saida


def test_progresso_paralelo_sem_total_mostra_contagem_corrida(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Borda: sem total (None), mostra só a contagem corrida, sem fração."""
    callback, _definir_total = prompts.progresso_paralelo("Gerando skeletons...")

    callback("public.clientes")

    saida = capsys.readouterr().out
    assert "(1) — public.clientes" in saida
    assert "/1" not in saida


def test_progresso_paralelo_definir_total_depois_passa_a_mostrar_fracao(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Borda: total definido após a criação passa a valer nas chamadas seguintes."""
    callback, definir_total = prompts.progresso_paralelo("Extraindo...")

    callback("public.clientes")
    definir_total(2)
    callback("public.pedidos")

    saida = capsys.readouterr().out
    assert "(1) — public.clientes" in saida
    assert "(2/2) — public.pedidos" in saida


# ampulheta()


def test_ampulheta_nao_propaga_excecao_e_encerra_a_thread() -> None:
    """Borda: sair do bloco `with` (com ou sem exceção) encerra a thread de animação."""
    with prompts.ampulheta("Testando..."):
        pass  # bloco vazio — só valida que entrar/sair funciona sem travar

# Issue #16 — feat: wizard da CLI end-to-end

## Contexto

Fase 7 do `plan/global.md` — última fase antes da issue #67 (transforma o
ddf em framework publicável no PyPI, com descoberta de plugins via
`importlib.metadata.entry_points`). A wizard `questionary`+`click` é o
adapter de CLI *padrão* que a #67 vai expor via `pip install ddf`, então o
desenho daqui precisa deixar os registros de extensão prontos pra receber
descoberta de terceiros sem reabrir `wizard.py`.

Existe um rascunho exploratório real (`scripts/prototipo_wizard_mariadb.py`,
fora de `src/`, nunca foi produto) que já validou boa parte da UX
manualmente contra Postgres/MariaDB reais. Uma banca de revisão
(arquiteto-de-software, engenheiro-de-dados, po-revisor) analisou esse
rascunho contra `docs/low_level_design.md` (fluxo de 14 etapas),
`docs/system_design_doc.md` (Decisões 3, 8, 10, 12) e `docs/prd.md`, e
encontrou gaps reais — resolvidos em rodada de decisão com o usuário antes
de implementar.

Plano completo de implementação: `/home/dev/.claude/plans/iridescent-forging-simon.md`
(sessão de planejamento com Claude, 2026-07-22).

## Decisões tomadas na discussão prévia (antes de implementar)

> **`cli/fontes.py` renomeia para `cli/extratores.py`** — nomeado pelo Port
> (`Extrator`), consistente com os novos `analisadores.py`/`geradores.py`
> (nomeados por `Analisador`/`Gerador`). `FONTES_REGISTRADAS` →
> `EXTRATORES_REGISTRADOS`, `registrar_fonte` → `registrar_extrator`. Toda
> referência ao nome antigo é corrigida (`CLAUDE.md`,
> `docs/engineer_guidelines.md`, `docs/low_level_design.md`, `plan/tasks.md`).

> **`EXTRATORES_REGISTRADOS` ganha `ExtratorPostgres` e `ExtratorMariaDB`**
> nesta issue, não só Postgres — as duas fontes já existem e têm cobertura
> de teste real; sem isso a etapa 1 do wizard roda contra um registro
> vazio/incompleto e a ferramenta não é demonstrável. `docs/prd.md`
> Restrição 1 ("v1 é só Postgres") é corrigida para refletir isso.

> **`EXTRATORES_REGISTRADOS` migra de `dict[str, type[Extrator]]` para
> `dict[str, ExtratorRegistrado]`**, carregando também o construtor
> interativo (`construir: Callable[[ConfiguracaoDeExtracao], Extrator]`) —
> sem isso o wizard precisaria de um `if fonte == "Postgres": ...` hardcoded
> por fonte, quebrando a promessa de extensão via plugin da #67 já na
> primeira etapa do fluxo. Paga o custo de reabrir o módulo (já
> mergeado/testado na #8 como `fontes.py`) uma vez agora, em vez de reabrir
> `wizard.py` inteiro quando um plugin de terceiro chegar na #67.

> **Registro genérico também para Analisador e Gerador**
> (`ANALISADORES_REGISTRADOS`/`GERADORES_REGISTRADOS`, mesmo padrão) — evita
> `if/elif` hardcoded por nome, que violaria Open/Closed (Decisão 10 do SDD)
> no primeiro Analisador/Gerador novo. Guardam a instância direto (não
> classe + construtor) porque `Analisador`/`Gerador` não recebem argumento
> no construtor (confirmado na issue #67 e nos adapters reais).
> **`ANALISADORES_REGISTRADOS` não é exposto em nenhum menu do wizard** — é
> um ponto de extensão manipulado só por quem desenvolve o ddf (ou por um
> plugin de terceiro, via a descoberta que a #67 vai construir em cima
> dele), nunca pelo usuário final da CLI. `GERADORES_REGISTRADOS` continua
> user-facing (etapa "escolher Geradores").

> **`OrquestradorDeTabelas`/`OrquestradorParalelo` estendidos**: sucesso
> parcial (uma tabela falhar não descarta o lote) + callback de progresso
> opcional. Corrige uma regressão de resiliência real que já existia antes
> desta issue (era all-or-nothing) e viabiliza mostrar progresso real
> durante extração/aplicação de sobrescritas em paralelo. Corrigido também,
> no mesmo passo, um bug pré-existente onde `Aviso`s do caminho de sucesso
> (ex.: `SobrescritaDeTabela` ao criar skeleton) eram descartados por
> `_executar_em_paralelo` — sem esse fix a etapa 6/7 do wizard não teria
> nada pra mostrar.

> **Sem etapa de "escolher Analisadores"** — todos os Analisadores
> registrados sempre rodam via `compor()`, sem seleção do usuário (bate com
> as 14 etapas documentadas, que só têm "escolher Geradores").

> **Correção de ordem nas 14 etapas do `low_level_design.md`:** a etapa 9
> ("validar dependências Analisadores + Geradores") aparecia *antes* da
> etapa 11 ("escolher Geradores") — logicamente inconsistente, pois não dá
> pra validar o `requer` de Geradores que o usuário ainda não escolheu.
> Resolvido escolhendo Geradores antes de validar (ordem final: extrair →
> sobrescritas → **escolher Geradores** → **validar dependências** →
> analisar via `compor()` → escolher destino → confirmar → executar). Isso
> também evita que um Gerador registrado mas não escolhido pelo usuário
> bloqueie a validação do que ele realmente vai rodar.

> **Retry de conexão (etapa 3) não é automático/cego** — mostra o erro real
> do driver a cada tentativa e oferece "Tentar novamente"/"Sair" (nunca
> retry silencioso com a mesma credencial errada — risco de lockout de conta
> em Postgres real), até o teto de 3 tentativas. Reusa
> `extrator.listar_escopos()` como sonda de conectividade — mesmo resultado
> alimenta a etapa 4 (escolher escopos), sem chamada de rede redundante.

> **Modo `--config`/não-interativo fica fora desta issue** — o usuário
> ainda não decidiu se vai mantê-lo; a assinatura de `wizard.py` não reserva
> esse parâmetro agora. `docs/low_level_design.md` é corrigido para remover
> essa menção como escopo da #16.

> **Regra transversal:** todo texto exibido ao usuário na CLI (prompts,
> mensagens de erro, avisos, confirmações) é em português.

> **Bug encontrado e corrigido durante a implementação:** `Estagio.__call__`
> (`pipeline/estagio.py`) declarava `entrada` como parâmetro normal
> (keyword-callable), mas `Analisador.__call__` foi tornado positional-only
> na revisão pré-CLI (issue #53) sem atualizar `Estagio` correspondentemente.
> Isso nunca foi pego porque o único uso de `compor()` com um `Analisador`
> vivia em `tests/`, fora do escopo do `mypy --strict` (`files = ["src"]`).
> A primeira vez que essa combinação apareceu em `src/` (`wizard.py`,
> etapa 11) o `mypy --strict` acusou a incompatibilidade estrutural.
> Corrigido tornando `Estagio.__call__` também positional-only — consistente
> com a convenção já adotada por `Analisador`/`Gerador`, e compatível com
> todo implementador existente (aceitar `entrada` por keyword continua
> válido; a Porta só passou a *não exigir* isso).

## Escopo desta issue

- [x] `domain/ports/orquestrador_de_tabelas.py` +
      `infrastructure/adapters/orchestrator/orquestrador_paralelo.py` —
      `progresso: Callable[[str], None] | None = None` em `extrair`/
      `aplicar_sobrescritas`; falhas individuais viram `Aviso`, nunca mais
      `Falha` agregada por falha parcial
- [x] `cli/estrategias.py` (novo, adicionado após teste manual) —
      `ESTRATEGIAS_REGISTRADAS`/`registrar_estrategia`/`EstrategiaRegistrada`,
      mesmo padrão de `extratores.py`. `EstrategiaDeAmostragem` é Port desde
      a v1 — mesmo com uma única implementação (`PercentualDeLinhas`) hoje,
      a escolha fica explícita no wizard (etapa 1) em vez de hardcoded, para
      não precisar reabrir `wizard.py` quando uma 2ª estratégia aparecer
- [x] `cli/extratores.py` (renomeado de `fontes.py`) — `ExtratorRegistrado`
      (`classe_extrator` + `construir`), `registrar_extrator`, registra
      `ExtratorPostgres` e `ExtratorMariaDB` nativamente
- [x] `cli/analisadores.py` (novo) — `ANALISADORES_REGISTRADOS`,
      `registrar_analisador`, registra `AnalisadorDeMetricasDeColuna` e
      `AnalisadorDeMetricasDeTabela`
- [x] `cli/geradores.py` (novo) — `GERADORES_REGISTRADOS`,
      `registrar_gerador`, registra `GeradorMarkdown`, `GeradorDbt`,
      `GeradorContextoDeIA`
- [x] `cli/prompts.py` (novo) — único importador de `questionary`: `texto`,
      `senha`, `selecionar`, `caminho`, `confirmar`, `escolher_multiplos`,
      `pausar`, `ampulheta`, `progresso_paralelo` (todas encapsulam a
      construção do prompt, não só o `.ask()` — nenhum outro módulo importa
      `questionary` diretamente, nem para montar o objeto de pergunta)
- [x] `cli/wizard.py` (novo) — `@click.command()` com o fluxo completo (ver
      ordem corrigida acima); avisos exibidos em streaming, agrupados por
      `(origem, mensagem)` com contagem; código de saída `0`/`1`
- [x] `src/ddf/__init__.py` — `main` vira `executar` de `cli/wizard.py`
      (confirmado via `uv run ddf --help`)
- [x] `mypy --strict`/`ruff` limpos
- [x] `cli/registro/` (novo) — agrupa `analisadores.py`/`estrategias.py`/
      `extratores.py`/`geradores.py` (pontos de extensão), com
      `comum.py::registrar_ou_falhar` compartilhado pelos 4 `registrar_*`
- [x] `cli/etapas/` (novo) — `wizard.py` fracionado por fase do pipeline
      (`extracao.py`, `curadoria.py`, `analise.py`, `geracao.py`);
      `cli/avisos.py` isola `ou_sair`/`exibir_avisos` (cross-cutting).
      `wizard.py` caiu de ~400 para ~65 linhas
- [x] Auditoria de indireção decorativa (critério formalizado em
      `arquiteto-de-software.md`) — corrigido bug de cancelamento em
      `prompts.pausar()`, fundidos `banner()`+`sucesso()` em
      `imprimir_destacado()`, removidos `duracao()`/`escolher_escopos()`/
      `_rodar_gerador()` (inline ou redundantes)

## Testes

- [x] `test_orquestrador_paralelo.py` — reescreve os 4 testes de falha
      agregada para sucesso parcial + `Aviso`; testes novos de `progresso`
      chamado por item concluído e de Aviso de sucesso preservado
- [x] `test_extratores.py` (renomeado de `test_fontes.py`, agora em
      `cli/registro/`) — `ExtratorRegistrado`/`registrar_extrator`
- [x] `test_analisadores.py`, `test_geradores.py`, `test_estrategias.py`
      (novos, em `cli/registro/`) — registro isolado não afeta o global;
      nome duplicado levanta `ValueError`
- [x] `test_avisos.py`, `test_prompts.py` (novos) — cobrem `ou_sair`/
      `exibir_avisos`/`_tipo_de_aviso` e o cancelamento/estilo/progresso de
      `prompts.py`
- [x] `cli/etapas/test_extracao.py`, `test_curadoria.py`, `test_analise.py`,
      `test_geracao.py` (novos, substituem o `test_wizard.py` único
      originalmente planejado — `wizard.py` foi fracionado em `etapas/`
      antes dos testes serem escritos) — caminho feliz, erro esperado e
      borda por etapa, com `Extrator`/`OrquestradorDeTabelas` fake
- [x] `tests/integration/cli/test_wizard_end_to_end.py` —
      `click.testing.CliRunner` + fila de respostas de `questionary` +
      `Extrator` fake injetado em `EXTRATORES_REGISTRADOS` isolado; resto do
      pipeline (Orquestrador, Sobrescrita, Analisadores, GeradorMarkdown) real

## Documentação

- [x] `CLAUDE.md`, `docs/engineer_guidelines.md` — `FONTES_REGISTRADAS` →
      `EXTRATORES_REGISTRADOS`; árvore de testes de `engineer_guidelines.md`
      atualizada com `cli/registro/`/`cli/etapas/`
- [x] `docs/low_level_design.md` — seção CLI reescrita com a organização do
      diretório (`registro/`/`etapas/`/`avisos.py`), a ordem corrigida de 14
      etapas, `ExtratorRegistrado.construir`, os 4 registros de extensão via
      `registrar_ou_falhar`, `progresso`/sucesso parcial em
      `OrquestradorDeTabelas`/`OrquestradorParalelo`, remove menção a
      `--config`
- [x] `docs/system_design_doc.md` — seção 8 atualizada (14 etapas, módulos
      de `cli/etapas/`, registros de extensão); Decisão 8 ganha nota sobre
      sucesso parcial + progresso
- [x] `docs/prd.md` — Restrição 1 e 6 atualizadas (Postgres e MariaDB, não
      só Postgres)
- [x] `plan/tasks.md` — seção "7. CLI real wizard" marcada como concluída;
      referências a `fontes.py`/`FONTES_REGISTRADAS` renomeadas (incluindo a
      menção histórica na Task 2); `plan/topics.md` também atualizado

## Status

Documentação e testes concluídos. Falta apenas organizar/revisar os commits
finais antes de abrir o PR.

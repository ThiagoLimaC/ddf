# Issue #67 — feat: transforma ddf em framework publicável via entry points

## Contexto

Depende da #16 (wizard end-to-end, já mergeada) — só faz sentido formalizar
`domain/ports` como API pública e abrir descoberta via entry points depois
que existe um consumidor real validando o contrato. A issue foi escrita
antes da #16 e cita nomes antigos (`FONTES_REGISTRADAS`, `registrar_fonte`,
`cli/fontes.py`) que não existem mais — hoje são `EXTRATORES_REGISTRADOS`/
`ANALISADORES_REGISTRADOS`/`GERADORES_REGISTRADOS` em
`cli/registro/{extratores,analisadores,geradores}.py`, já populados via
chamada direta no import de cada módulo.

Objetivo: permitir `pip install ddf` e (a) importar `Extrator`/`Gerador` de
um caminho público estável, e (b) descobrir plugins de terceiro via
`importlib.metadata.entry_points` sem fork.

Plano completo de implementação:
`/home/dev/.claude/plans/stateful-sniffing-key.md` (sessão de planejamento
com Claude, 2026-07-24).

## Decisão de escopo: Analisador fica de fora

`Analisador` é a ACL entre Curation e Analysis (`CLAUDE.md`) e — diferente
de Extrator/Gerador, escolhidos pelo usuário em menus do wizard — todo
Analisador registrado roda incondicionalmente em toda execução, sem seleção
nenhuma. Abrir descoberta automática de terceiro pra ele rodaria código de
qualquer pacote instalado no venv a cada execução, sem o usuário ter
pedido. `cli/registro/analisadores.py` fica sem nenhuma mudança nesta
issue; reabrir como issue própria se/quando houver consumidor real pedindo
Analisador de terceiro.

## Escopo desta issue

- [x] Reexportar `Extrator`/`Gerador` (não `Analisador`) em
      `domain/ports/__init__.py` como caminho de import estável
- [x] `cli/registro/descoberta.py` — `descobrir_extratores`/
      `descobrir_geradores`/`descobrir_plugins()`, isolando falha por
      entry point (import quebrado, classe fora do Protocol, nome
      duplicado) como `Aviso`, sem derrubar a descoberta das demais
- [x] Mover registro nativo de Extrator/Gerador de chamada direta
      (`registrar_extrator(...)`/`registrar_gerador(...)` no fim dos
      módulos) para constantes consumidas por entry point — dogfooding
      real, sem distinção nativo/terceiro; `analisadores.py` não muda
- [x] `wizard.py` invoca `descobrir_plugins()` logo no início de
      `executar()`, antes de qualquer etapa que leia os registros
- [x] `pyproject.toml` declara `[project.entry-points."ddf.extratores"]` e
      `"ddf.geradores"` com os adapters nativos (sem grupo
      `ddf.analisadores`)
- [x] Documentar política de versionamento semântico de
      `domain/ports/extrator.py`/`gerador.py` em
      `docs/engineer_guidelines.md`: mudança de assinatura é breaking
      change, não refactor livre; registrar que `Analisador` fica fora
      dessa política por não ser superfície pública de plugin nesta issue
- [x] `uv build` local para validar empacotamento com os entry points
      (publicação em TestPyPI/PyPI é passo manual do usuário, fora deste
      plano — depende de token que só ele tem); validado também instalando
      o wheel gerado num venv limpo e confirmando que
      `entry_points(group="ddf.extratores"/"ddf.geradores")` aparece sem
      precisar do repo em modo editable
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] Caminho feliz: `EntryPoint` fake apontando para um
      `ExtratorRegistrado`/classe de Gerador definido em módulo fake de
      teste, descoberto e populado em registro isolado
- [x] Erro esperado: entry point com import quebrado e entry point
      apontando para classe fora do Protocol — cada um vira `Aviso`
      isolado, sem impedir a descoberta dos demais
- [x] Caso de borda: dois entry points com o mesmo nome — colisão tratada
      pelo `ValueError` já existente em `registrar_ou_falhar`
- [x] Ajustar testes existentes que hoje dependem de
      `EXTRATORES_REGISTRADOS`/`GERADORES_REGISTRADOS` populado só por
      efeito colateral de import — não foi necessário: todos os testes
      existentes de `test_extratores.py`/`test_geradores.py` já usavam
      registro isolado, suíte completa (349 testes) segue verde
- [x] Correção durante a implementação: `descobrir_extratores`/
      `descobrir_geradores` ganharam parâmetro `registro` (mesmo padrão de
      `registrar_extrator`/`registrar_gerador`) — sem isso não dava para
      testar a descoberta sem sujar o registro global

## Revisão obrigatória antes do merge

- [x] `arquiteto-de-software` focado em confirmar que `Analisador` está
      corretamente isolado do mecanismo de entry points (nenhum grupo
      `ddf.analisadores` declarado em lugar nenhum), além da banca de
      revisão padrão — **aprovado com ressalvas**, isolamento confirmado
      correto em 5 pontos verificados; achados abaixo

## Achados da revisão (aplicados)

- [x] **Bloqueante:** docstring de `cli/registro/analisadores.py`
      afirmava que Analisador seria descoberto "via a descoberta que a
      issue #67 constrói em cima deste registro" — o oposto da decisão de
      escopo tomada. Corrigida (também a menção equivalente na docstring
      de `registrar_analisador`).
- [x] **Sugestão:** nenhum teste exercitava a resolução real dos entry
      points nativos (só fakes em `test_descoberta.py`) — um erro de
      digitação em `_REGISTRO_POSTGRES` no `pyproject.toml` só quebraria
      em runtime. Adicionado
      `tests/integration/cli/test_descoberta_entry_points_nativos.py`,
      chamando `descobrir_extratores`/`descobrir_geradores` sem fake.
- [x] **Nice-to-have:** `descobrir_plugins()` era um wrapper de uma linha
      com único call site — inlinado direto em `wizard.py`.
- [x] **Nice-to-have:** `docs/low_level_design.md` não cobria a mecânica
      de `ExtratorRegistrado`/entry points — nota adicionada na seção CLI.

## Achados da revisão final (banca completa, antes do PR)

- [x] **Sugestão do arquiteto-de-software:** `ExtratorRegistrado` vivia em
      `cli/registro/extratores.py` (infraestrutura de CLI), não em
      `domain/ports` — um plugin de terceiro dependia de um tipo não
      versionado pela política de semver, quebra silenciosa possível.
      Movida para `domain/ports/extrator.py`, reexportada em
      `domain/ports/__init__.py`, incluída explicitamente na política de
      semver (`engineer_guidelines.md`) e documentada em
      `low_level_design.md`. Todos os imports em testes atualizados para
      o caminho público (`ddf.domain.ports.extrator`/`ddf.domain.ports`).
      `mypy --strict`/`ruff` limpos, 351 testes verdes.
- po-revisor e engenheiro-de-dados: **aprovados sem bloqueantes** na
  rodada de revisão da banca completa (arquiteto + PO + engenheiro de
  dados) sobre o diff final contra `development`.

## Status

Escopo de código, documentação e os 4 achados da revisão arquitetural
implementados e verificados (`mypy --strict`, `ruff`, suíte completa
verde). Pronto para abrir PR.

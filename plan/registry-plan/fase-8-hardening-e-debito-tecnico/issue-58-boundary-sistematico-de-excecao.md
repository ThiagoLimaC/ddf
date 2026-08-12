# Issue #58 — feat: adiciona boundary sistemático de exceção não prevista (executar_com_seguranca)

## Contexto

Achado de arquitetura da auditoria pré-CLI (issue #56, Fase 3), decisão do
arquiteto de software em rodada de follow-up — extraído de #56 para
permitir merge independente.

Nenhuma camada do pipeline captura `Exception` genérica: nem `compor()`
(`pipeline/compor.py`) nem `OrquestradorParalelo._executar_em_paralelo`
(`futuro.result()` relança qualquer exceção sem interceptar). O contrato
"nunca propaga exceção crua" (`Resultado`, seção Shared do
`low_level_design.md`) dependia inteiramente da disciplina de quem escreve
cada Adapter — o mesmo risco existe em Extrator (rodando em thread do
Orquestrador) e Gerador, não só no caso pontual do `ARRAY` (issue #57).

Plano completo de implementação: `/home/dev/.claude/plans/cosmic-exploring-matsumoto.md`
(sessão de planejamento com Claude, 2026-07-21).

## Escopo desta issue

- [x] `pipeline/seguranca.py` — `executar_com_seguranca(nome_estagio,
      funcao) -> Resultado` — converte qualquer `Exception` não antecipada
      em `Falha`, preservando nome do Estágio + tipo da exceção original
      (log interno via `logging.exception`, causa raiz continua visível,
      não vira rede de segurança permanente); `except Exception`, não
      `BaseException` — não intercepta `KeyboardInterrupt`/`SystemExit`
- [x] Aplicada em `compor()` — envolve cada `estagio(valor)`, nomeando pelo
      tipo/`__name__` do Estagio
- [x] Aplicada em `OrquestradorParalelo._executar_em_paralelo` — novo
      parâmetro `nome_estagio`, combinado com o identificador do item na
      mensagem; `extrair` passa `"Extrator"`, `aplicar_sobrescritas` passa
      `"Sobrescrita"`
- [x] Aplicada em `scripts/prototipo_wizard_mariadb.py` (as 3 chamadas de
      Gerador) — Task 7/CLI real ainda não existe, este é o único ponto de
      chamada de Gerador hoje em `src`/`scripts`
- [x] Não substitui a conversão de exceções esperadas e específicas já
      feita por cada Adapter (ex.: `OperationalError` → `Falha("Não foi
      possível conectar...")`) — é chamada em volta dessas chamadas, não
      dentro delas
- [x] Nova Decisão de Arquitetura 12 em `docs/system_design_doc.md` (mesmo
      padrão da Decisão 11)
- [x] Notas no `low_level_design.md` (`compor`, `OrquestradorParalelo` e
      seção CLI — Task 7 obrigada a repetir o padrão em torno de cada
      Gerador)
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] `test_seguranca.py` (função nova, isolada)
- [x] `test_compor.py`: `Estagio` que levanta exceção arbitrária vira
      `Falha`, sem quebrar os casos já existentes de `Falha` explícita
- [x] `test_orquestrador_paralelo.py`: worker que levanta exceção em
      paralelo acumula como falha isolada, sem quebrar as outras tabelas do
      lote — mesma política de acumulação já testada para `Falha` explícita
- [x] `pytest` completo (unit + integration) verde antes do PR

## Status

Mergeada em `development` via PR (commit de merge `4cab736`). Branch
`feat/58-boundary-sistematico-de-excecao` removida (local e remoto) após o
merge.

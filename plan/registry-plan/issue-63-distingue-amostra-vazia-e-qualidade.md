# Issue #63 — fix: distingue amostra vazia de dado limpo e outras melhorias de qualidade dos artefatos

## Contexto

Sugestões de qualidade da auditoria de engenharia de dados pré-CLI (issue
#56, Fase 2) — extraído de #56 para permitir merge independente, depois que
#57 (Fase 1) já estava em `development` (dependência técnica: os testes de
determinismo dos Geradores tocados aqui já existiam desde a Fase 1).

Plano completo de implementação: `/home/dev/.claude/plans/cosmic-exploring-matsumoto.md`
(sessão de planejamento com Claude, 2026-07-21).

## Decisão tomada na discussão prévia

> **`relationships` do dbt em FK composta — documentar a limitação, não
> modelar FK composta de verdade.** Modelar de verdade exigiria agrupar
> colunas de uma mesma constraint composta no Extraction Context (hoje
> `referencia` é por coluna) — mudança bem maior que as outras 4 sugestões
> desta issue, tocando 3 Bounded Contexts. A própria issue #56 aceita
> documentar como saída válida. Confirmado com o usuário (PO).

## Escopo desta issue

- [x] Completude/percentuais distinguem "sem evidência" (amostra vazia) de
      "0% nulo" na apresentação (`GeradorMarkdown._formatar_completude`/
      `_linha_qualidade`, `GeradorContextoDeIA` ganha `amostra_vazia: bool`
      ao lado de `completude`); `GeradorDbt._sugestoes_de_teste` exige
      `tamanho_amostra > 0` antes de considerar a métrica amostral pra
      `unique`/`not_null` (fato estrutural do schema — `coluna.nao_nulavel`/
      `unica` — continua valendo independente disso)
- [x] `Aviso` quando `tamanho_amostra > total_linhas` em ambos os
      Extratores (`ExtratorPostgres`/`ExtratorMariaDB`) — sintoma de
      `reltuples`/`TABLE_ROWS` desatualizado sem `ANALYZE` recente
- [x] Custo de amostragem full-scan documentado em `PercentualDeLinhas`,
      `EstrategiaDeAmostragem` (Port) e `system_design_doc.md` — que também
      corrigiu menção desatualizada a `LimiteAleatorio`, substituída há
      tempos por `PercentualDeLinhas`
- [x] Limitação de `relationships`/FK composta documentada em
      `_sugestoes_de_teste` (`gerador_dbt.py`) e `low_level_design.md`
- [x] `generated_at` (ISO 8601, `datetime.now(UTC)`) em `GeradorMarkdown`
      (rodapé de `index.md` e de cada `.md` de tabela), `GeradorDbt`
      (`dbt_project.yml`, bloco `meta`) e `GeradorContextoDeIA`
      (`index.json`, chave de topo) — calculado uma vez no `__call__` de
      cada Gerador (momento da geração, não da extração)
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] Casos novos nos testes já existentes dos Geradores/Extratores afetados
      (`test_gerador_markdown.py`, `test_gerador_contexto_de_ia.py`,
      `test_gerador_dbt.py`, `test_extrator_postgres.py`,
      `test_extrator_mariadb.py`) — sem arquivo de teste novo
- [x] Testes de determinismo byte-a-byte existentes (`test_gerador_dbt.py`,
      `test_gerador_contexto_de_ia.py`) ajustados para excluir o campo
      `generated_at`/`meta.generated_at` (variável por natureza) da
      comparação, parseando o artefato em vez de comparar texto bruto
- [x] `pytest` completo (unit + integration) verde antes do PR

## Status

Mergeada em `development` via PR (commit de merge `0c9b88d`). Branch
`fix/63-distingue-amostra-vazia-e-melhorias-de-qualidade` removida (local e
remoto) após o merge.

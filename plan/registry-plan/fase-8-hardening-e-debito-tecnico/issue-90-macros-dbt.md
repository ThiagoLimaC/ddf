# Issue #90 — macros dbt customizadas (formato_detectado + teste soft de nulos/unicidade)

Plano completo revisado em
`/home/dev/.claude/plans/pode-abrir-em-plan-shimmering-piglet.md` (sessão de
planejamento). Banca de revisão (arquiteto-de-software + engenheiro-de-dados +
po-revisor) rodada sobre o plano antes da implementação, apesar de a própria
issue não exigir banca completa — achado bloqueante: a premissa original
(`dbt.regexp_like` como macro builtin cross-adapter do dbt-core) é factualmente
incorreta, não existe. Decisões fechadas com o usuário:

- Threshold soft: **10% nulo / 95% único** (não 5%/90% — mais afastado da faixa
  de maior incerteza estatística perto do piso de amostra, evita "piscar" entre
  reextrações por ruído amostral), **+ piso de amostra ≥ 100** reaproveitando o
  mesmo piso já usado pelo Analisador.
- `matches_format`: dispatch por adapter (Postgres + MariaDB) dentro desta
  própria issue, **um arquivo por adapter** (não um único arquivo com dispatch
  embutido) — decisão do usuário: força quem for dar suporte a uma engine nova
  a criar um arquivo novo implementando o contrato, ponto de extensão visível
  no filesystem.

## 1. `templates/macros/matches_format/` (arquivos estáticos, não `.jinja2`)

- [x] `matches_format.sql` — `{% test matches_format %}` + dict de patterns
      fixo (cópia literal de `_REGEXES`) + `default__validate_format` que
      falha explicitamente para engine não suportada
- [x] `postgres__validate_format.sql` — via `~*` (case-insensitive, paridade
      com `re.IGNORECASE` do regex de email)
- [x] `mariadb__validate_format.sql` — via `REGEXP`

## 2. `_sugestoes_de_teste` (`gerador_dbt.py`)

- [x] Constantes `_LIMITE_NULO_SOFT = 10.0`, `_LIMITE_UNICO_SOFT = 95.0`,
      `_TAMANHO_AMOSTRA_MINIMO_SOFT = 100` (redefinida localmente, mesmo padrão
      já usado por `GeradorContextoDeIA._TAMANHO_AMOSTRA_MINIMO_ENUM` — não
      importa a constante privada do Analisador)
- [x] Branch `matches_format` quando `metrica.formato_detectado is not None`
- [x] Branch soft-nulo: `dbt_utils.not_null_proportion` (já existe pronto no
      pacote, sem macro novo) com `severity: warn` — `warn_if` puro não dava
      pra expressar proporção dinâmica de forma limpa, `not_null_proportion`
      resolve isso melhor que reimplementar
- [x] Branch soft-único: `dbt_utils` não tem equivalente de "% único"
      (`unique` builtin conta duplicatas) — macro custom
      `unique_percentage_at_least` (nome em inglês), SQL ANSI puro sem
      dispatch por adapter
- [x] Guards: `_precisa_teste_soft_nulo`/`_precisa_teste_soft_unico` —
      `tamanho_amostra >= 100`, coluna não é PK nem estruturalmente
      not-nullable/única, mútua exclusão explícita com o teste hard
      correspondente

## 3. Escrita condicional + remoção de órfão em `GeradorDbt.__call__`

- [x] `usa_dbt_utils` (packages.yml) estendido: agora também True quando há
      consumidor de `not_null_proportion`, não só `restricoes_unicas` (#89)
- [x] `macros/matches_format/` (3 arquivos) só escrito com consumidor real
      no lote (`_precisa_matches_format`); removido via `shutil.rmtree`
      quando fica órfão
- [x] `macros/unique_percentage_at_least.sql` só escrito com consumidor real
      (`_precisa_unique_percentage_at_least`); removido via
      `unlink(missing_ok=True)` quando órfão
- [x] `mypy --strict` + `ruff check` limpos em `gerador_dbt.py`

## 4. Teste de contrato Python

- [x] `set(detector_de_formato._REGEXES.keys())` vs. chaves de formato
      embutidas em `matches_format.sql` (extração via regex do bloco
      `{% set patterns = {...} %}`)
- [x] Fixado `test_accepted_values_omitido_quando_top10_cobre_pouco_da_amostra`
      (regressão legítima: `percentual_nulo=1.0` do fixture original caía na
      faixa soft nova, mudado pra 20.0 pra isolar a asserção original)
- [x] `pytest tests/unit` completo — 422 testes passando, sem regressão

## 5. Testes

- [x] `_sugestoes_de_teste`: feliz/estrutural/borda para as 3 branches novas
      (11 testes: matches_format feliz; soft-nulo feliz/estrutural
      not_nullable/amostra abaixo do piso/limite exato/acima do limite/PK;
      soft-único feliz/estrutural unica/amostra abaixo do piso/abaixo do
      limite)
- [x] `GeradorDbt.__call__`: macros escritos só com consumidor, removidos
      quando órfãos (7 testes: matches_format/ ausente sem consumidor,
      gerado com conteúdo igual ao template, órfão removido;
      unique_percentage_at_least.sql idem; packages.yml também gerado só
      por not_null_proportion, sem restricoes_unicas)
- [x] `pytest tests/unit` completo — 440 testes passando, sem regressão

## 6. Documentação

- [x] `README.md.jinja2` — nota sobre os testes novos (severity warn) +
      limitação de engines de `matches_format` (condicional a
      `usa_matches_format`); nota de `dbt_utils` generalizada (não é mais só
      `unique_combination_of_columns`, agora também `not_null_proportion`)
- [x] `docs/low_level_design.md` — seção `GeradorDbt`: tabela de condições
      novas, `matches_format` (dispatch por adapter, arquivo por engine,
      teste de contrato), testes soft (justificativa estatística dos
      thresholds 10%/95%, `dbt_utils.not_null_proportion` vs. macro custom
      `unique_percentage_at_least`); parágrafo de "Saída" atualizado
      (`packages.yml` com 2 consumidores possíveis)
- [x] `plan/tasks.md` — reabertura de escopo da #90 na seção 6

## Verificação final

- [x] `mypy --strict` (73 arquivos em `src/`) + `ruff check` (`src` + `tests`)
      — limpos
- [x] `pytest tests/unit` — 440 testes passando, sem regressão
- [ ] Geração manual de projeto dbt de exemplo cobrindo as 3 sugestões novas
- [ ] `dbt compile`/`dbt parse` contra Postgres e MariaDB, se disponível no
      ambiente — achado da banca: dispatch por adapter não pode ficar
      validado só "no papel". Pendente: exige `dbt-core` + adapters
      instalados, fora do escopo de dependências do próprio ddf

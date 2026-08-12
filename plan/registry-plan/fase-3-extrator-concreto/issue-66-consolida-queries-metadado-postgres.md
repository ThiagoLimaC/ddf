# Issue #66 — perf: consolida queries de metadado do ExtratorPostgres com cache por schema (N+1)

## Contexto

Última fase da auditoria de engenharia de dados pré-CLI (issue #56, Fase 4 —
não bloqueante), extraída para issue própria depois que #57 (Fase 1), #58
(Fase 3) e #63 (Fase 2) já estavam mergeadas em `development`.

`ExtratorPostgres.extrair_tabela` faz 6 round-trips sequenciais por tabela
(colunas, PK, FK, UNIQUE, total_linhas, amostra) — real em schemas com
500-1000 tabelas, mas otimização interna de um único Adapter atrás de um
Port que não muda. Não bloqueia a Task 7.

## Decisões tomadas na discussão prévia (sessão de planejamento)

> **Filtro `relkind IN ('r', 'p')` em `_TOTAL_LINHAS_SQL`** — achado do
> `engenheiro-de-dados` ao revisar o desenho desta fase, bug pré-existente
> (não introduzido aqui): tabela particionada é `BASE TABLE` em
> `information_schema.tables`, mas `reltuples` do pai particionado só
> agrega os filhos a partir do PG14 — pode ficar em 0 mesmo com dado real
> nas partições em versões anteriores ou sem `ANALYZE` recente no pai.
> Postgres não permite colisão de nome entre tabela/view/sequence no mesmo
> schema, então o join por nome já blindava contra pegar a relação errada
> por coincidência de design, não por robustez da query — o filtro
> `relkind` é defesa explícita, não correção de um bug já observado em
> produção.

> **Ressalva de medição** — sem Postgres gerenciado real disponível neste
> ambiente pra validar a 50-100+ tabelas como o critério de aceite original
> pede. O benchmark via testcontainers local mede a *direção* do ganho
> (round-trip por schema em vez de por tabela) mas **subestima** o ganho
> real — round-trip em socket/loopback Docker é sub-milissegundo, Postgres
> gerenciado real fica em 0,3–2ms (mais em cross-AZ). O número medido é um
> piso conservador, documentado como tal no PR, não a expectativa de
> produção. Desenho do benchmark (múltiplos pontos, múltiplos schemas,
> `ANALYZE` explícito) validado com o `engenheiro-de-dados`.

Plano completo de implementação (contexto da Fase 4 original):
`/home/dev/.claude/plans/cosmic-exploring-matsumoto.md` (sessão de
planejamento com Claude, 2026-07-21).

## Escopo desta issue

- [x] Consolidar as 5 queries de metadado (colunas, PK, FK, UNIQUE,
      total_linhas) em uma única query por schema, filtrando client-side
      por tabela, em vez de uma query por tabela — as 5 constantes SQL
      passaram a trazer `table_name`/`relname` como 1ª coluna, agrupadas em
      `dict[str, ...]` por tabela (`_MetadadosDoSchema`, via `defaultdict`)
- [x] Cache por schema em `ExtratorPostgres` com double-checked locking,
      mesmo padrão que já protege `_obter_pool`/`_lock_pool` —
      `_obter_metadados_schema(schema)` novo, `self._cache_schemas` +
      `self._lock_cache_schemas`; `extrair_tabela` só roda a query de
      amostra (`TABLESAMPLE`) por tabela, resto vem do cache
- [x] Filtro `relkind IN ('r', 'p')` em `_TOTAL_LINHAS_SQL` (só existe mais
      a versão consolidada — a per-tabela foi removida, não duplicada)
- [x] Benchmark sintético via testcontainers: 10/50/100/200 tabelas, 4
      schemas, 5-20 colunas por tabela, PK/FK (cadeia dentro do schema,
      cross-schema a cada 10 tabelas, 1 auto-referência) e UNIQUE avulso a
      cada 5 tabelas, `ANALYZE` explícito após popular
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] Unit: cache populado uma vez por schema mesmo com múltiplas chamadas
      concorrentes (thread-safety) — mockado, mesmo padrão de
      `test_primeiro_uso_concorrente_cria_pool_uma_unica_vez`
- [x] Unit: 2ª extração no mesmo schema reaproveita o cache (nº de
      `fetchall`/conexões determinístico, não só "não quebra")
- [x] Integração: corretude ponta a ponta idêntica antes/depois da
      consolidação (testcontainers Postgres real) — os 14 testes de
      integração já existentes (FK composta, FK cross-schema, UNIQUE
      nomeada/solta, ARRAY) passaram sem alteração contra a query
      consolidada, mais 1 teste novo de reaproveitamento de cache
      (2 tabelas, 1 instância)
- [x] Integração: teste de concorrência cobrindo múltiplas tabelas do
      mesmo schema em paralelo via `OrquestradorParalelo` real (não
      mockado) contra Postgres real
- [x] Benchmark: matriz de tempo (10/50/100/200 tabelas) documentada
      abaixo, com a ressalva de piso conservador
- [x] `pytest` completo (unit + integration) verde antes do PR

## Resultado do benchmark

Baseline "antes" recriado só no arquivo de benchmark (as 5 queries
per-tabela removidas de `src/`, fiéis ao texto original) vs. "depois"
(`_obter_metadados_schema` real). Nº de round-trips é determinístico —
`queries_depois = 5 × nº de schemas`, nunca `5 × nº de tabelas`; tempo de
parede é informativo (rodar com `-s`), sujeito à ressalva de piso
conservador (Docker local, round-trip sub-milissegundo):

| tabelas | schemas | queries antes | queries depois | ganho medido |
|--------:|--------:|---------------:|----------------:|-------------:|
|      10 |       4 |             50 |               20 |     ~1.7-1.9x |
|      50 |       4 |            250 |               20 |     ~7.8-10x  |
|     100 |       4 |            500 |               20 |    ~18.8-21.3x |
|     200 |       4 |           1000 |               20 |    ~40.1-53.7x |

`queries_depois` fica **fixo em 20** (5 × 4 schemas) independente do nº de
tabelas — é essa razão, não o tempo de parede medido, que sustenta o ganho
estrutural (O(schemas) em vez de O(tabelas)), válida também contra Postgres
gerenciado real, onde o ganho absoluto de tempo tende a ser maior (latência
de rede por round-trip bem acima do piso de loopback local).

## Status

Implementado e testado em `refactor/66-consolida-queries-metadado-postgres`
(cortada de `development` já com #57/#58/#63 mergeadas). Falta abrir o PR
pra `development`.

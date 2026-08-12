bl# Issue #104 — perf: consolida queries de metadado do ExtratorMariaDB com cache por schema (N+1)

## Contexto

`ExtratorMariaDB.extrair_tabela` refaz 6 round-trips de `information_schema`
**por tabela** (colunas, PK, FK, UNIQUE, total_linhas, detecção de coluna
JSON via CHECK), sem nenhum cache — evidência empírica registrada na
issue: extração real de 845 tabelas MariaDB (maioria vazia) levou 364s com
`max_trabalhadores=8` (~431ms/tabela em média), tempo incompatível com
"nada para processar", consistente com overhead de round-trip de catálogo
repetido por tabela.

`ExtratorPostgres` já recebeu o mesmo tratamento na issue #66
(`_MetadadosDoSchema` + `_obter_metadados_schema` com double-checked
locking, mesmo padrão de `_obter_pool`/`_lock_pool`) — este plano aplica o
mesmo padrão ao `ExtratorMariaDB`.

Diferença estrutural real que o Postgres não tem: **nomes de constraint no
MariaDB são escopados por tabela, não por schema** (já documentado em
`mariadb/_queries.py`, corrigido uma vez na issue #44 para UNIQUE).
Consolidar para schema-wide sem preservar esse cruzamento reintroduziria
aquele bug. Otimização interna de um Adapter atrás de uma Port
(`Extrator`) que não muda — reversível, sem risco arquitetural.

Reabertura de escopo decidida durante o planejamento desta issue (achado
do `engenheiro-de-dados` na banca de revisão do plano, confirmado
empiricamente pelo usuário e o próprio Claude contra `mariadb:11` real via
Docker): o mesmo tipo de colisão de nome de constraint também afeta
`_COLUNAS_JSON_SQL` (detecção de coluna JSON via CHECK) — só que ali o bug
**já existe hoje**, antes desta issue, mascarado pelo padrão per-tabela
atual (só uma tabela é consultada por vez). A premissa original do código
("`CHECK_CONSTRAINTS` não tem coluna de tabela, então só o cross-check
contra as colunas reais evita atribuir o CHECK de uma tabela a outra") foi
**verificada como falsa**: `information_schema.CHECK_CONSTRAINTS` **tem**
`TABLE_NAME` (confirmado via `information_schema.columns` e via teste
direto — duas tabelas do mesmo schema com `CONSTRAINT_NAME` idêntico
retornam `TABLE_NAME`/`CHECK_CLAUSE` corretamente atribuídos, sem
fan-out). A query atual faz um `JOIN` desnecessário com
`table_constraints` só pra filtrar `constraint_type = 'CHECK'` —
redundante, já que `CHECK_CONSTRAINTS` só contém constraints desse tipo —
e por isso nunca usa a coluna `TABLE_NAME` que já resolveria o cruzamento
sozinha. A pedido explícito do usuário, o bug é **corrigido** nesta issue,
não só documentado como limitação conhecida.

Plano revisado pela banca completa (arquiteto-de-software,
engenheiro-de-dados, po-revisor) antes da implementação — os três
aprovaram com ressalvas, incorporadas ao plano antes do código.

## Escopo desta issue

- [x] `mariadb/_queries.py` — as 6 queries per-tabela reescritas para
      consultar o escopo inteiro de uma vez, mesmo nome de constante de
      antes (`_COLUNAS_SQL`, `_CHAVES_PRIMARIAS_SQL`,
      `_CHAVES_ESTRANGEIRAS_SQL`, `_TOTAL_LINHAS_SQL`, `_COLUNAS_UNICAS_SQL`,
      `_COLUNAS_JSON_SQL`) — `_COLUNAS_SQL`/`_CHAVES_PRIMARIAS_SQL`/
      `_CHAVES_ESTRANGEIRAS_SQL`/`_TOTAL_LINHAS_SQL` (trocas triviais, perdem
      `table_name = %s` do WHERE); `_COLUNAS_UNICAS_SQL` (mantém
      `table_name` no JOIN tc↔kcu, só remove do WHERE — o agrupamento em
      Python passa a ser por `(table_name, constraint_name)`, não só
      `constraint_name`); `_COLUNAS_JSON_SQL` (reescrita, não só
      consolidada — remove o JOIN com `table_constraints`, seleciona
      `table_name, check_clause` direto de `check_constraints`, corrige o
      bug pré-existente de fan-out por colisão de `constraint_name` entre
      tabelas)
- [x] `extrator_mariadb.py` — `_MetadadosDoSchema` (NamedTuple) +
      `_obter_metadados_schema(escopo)` com double-checked locking
      (`self._cache_schemas`/`self._lock_cache_schemas`, mesmo padrão de
      `_obter_pool`/`_lock_pool`); **sem** `restricoes_fk_compostas_por_tabela`
      pré-computado (divergência deliberada do Postgres —
      `construir_restricoes_fk_compostas` é CPU-only, reconstruída por
      tabela em `extrair_tabela` a partir de `fks_por_tabela` já cacheado,
      sem custo de round-trip extra)
- [x] `extrair_tabela` reescrito: só roda a query de amostra por tabela
      (não cacheável por schema); resto vem do cache.
      `_promover_booleanos_pela_amostra` inalterada. Sem mudança de
      assinatura pública — Port `Extrator` intocada
- [x] Benchmark sintético em
      `tests/integration/extractors/mariadb/test_extrator_mariadb_benchmark.py`
      (mesmo padrão da #66): 10/50/100/200 tabelas, 4 escopos, PK/FK
      (cadeia + cross-escopo + auto-referência), UNIQUE avulso — mais 2
      casos de colisão no próprio lote de volume: UNIQUE de nome idêntico
      entre 2 tabelas (preserva #44) e CHECK de nome idêntico entre 2
      tabelas, uma JSON de verdade outra não (prova a correção desta
      issue)
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] Unit: cache populado uma vez por schema mesmo com chamadas
      concorrentes (mockado, mesmo padrão do `ExtratorPostgres`)
- [x] Unit: 2ª extração no mesmo schema reaproveita cache (nº de
      `execute` determinístico)
- [x] Unit: regressão direcionada de colisão UNIQUE (2 tabelas fake do
      mesmo schema, `constraint_name` idêntico) — preserva o
      comportamento correto desde a #44
- [x] Unit: teste novo de colisão CHECK/JSON (2 tabelas fake do mesmo
      schema, `constraint_name` idêntico, uma JSON outra não) — prova a
      correção do bug pré-existente, não só ausência de regressão
- [x] Integração: suite atual (FK cross-database, promoção BOOLEAN, PK/FK
      composta) passa sem alteração contra a query consolidada
- [x] Integração: teste de concorrência via `OrquestradorParalelo` real
      (não mockado), múltiplas tabelas do mesmo schema em paralelo
- [x] Integração: corretude ponta a ponta do cenário de colisão
      UNIQUE/CHECK contra MariaDB 11 real (fixture nova
      `restricoes.relatorios`/`restricoes.contadores`, reproduzida e
      validada contra MariaDB 11 real via Docker antes da implementação)
- [x] Benchmark: matriz de tempo (10/50/100/200 tabelas) documentada
      abaixo, incluindo nº de round-trips antes/depois explicitamente
      (não só tempo de parede — ressalva de piso conservador, mesmo
      critério da #66)
- [x] `pytest` completo (unit + integration, 535 testes) verde antes do PR

## Ordem de commits

1. `perf(mariadb)`: `_queries.py` (as 6 queries reescritas pra consultar
   por escopo, substituindo as versões per-tabela no mesmo commit) +
   `_MetadadosDoSchema` +
   `_obter_metadados_schema` + `extrair_tabela` reescrito. Segue o
   precedente da #66 ("remover, não duplicar").
2. `test(mariadb)`: unit tests novos (cache, concorrência, regressão de
   colisão UNIQUE/CHECK).
3. `test(mariadb)`: testes de integração novos/ajustados.
4. `test(mariadb)`: benchmark sintético + resultado documentado no PR.

## Fora de escopo

- `ExtratorPostgres` (já feito na #66), contrato da Port `Extrator`,
  qualquer Analisador/Gerador.

## Nota pós-implementação: teste real do usuário e esclarecimento sobre FK composta

Após a implementação, o usuário rodou o wizard real contra um MariaDB
gerenciado com 843 tabelas em 5-6 escopos e reportou (a) duração similar
ou pior que o baseline da issue (364s/845 tabelas) e (b) avisos de "mais
de uma FK" em colunas que ele esperava ver como `restricoes_fk_compostas`.

Investigação:
- **FK composta**: os avisos ("Coluna 'X' tem mais de uma FK") indicam
  **2+ constraints separadas de uma única coluna** apontando pra tabelas
  diferentes — não uma FK composta (que é 1 constraint abrangendo 2+
  colunas). `_CHAVES_ESTRANGEIRAS_SQL` manteve o mesmo filtro
  (`referenced_table_name IS NOT NULL`) e a mesma semântica de linhas da
  versão per-tabela (só mudou o escopo da consulta, não o que cada tabela
  recebe) — confirmado comparando contra
  `git show 2e76c87^:.../mariadb/_queries.py`. Esse comportamento (e o
  `Aviso` de `construir_colunas_fk`) já existe desde a #56, não foi
  introduzido nem alterado por esta issue.
- **Performance**: com 5-6 escopos e ~843 tabelas, a redução teórica de
  round-trips é grande (~7 queries/tabela → ~6/escopo + 1 amostra/tabela,
  ~6-7x menos round-trips). O usuário confirmou que a comparação foi entre
  execuções em dias diferentes, com variância de rede reconhecida
  (ambiente gerenciado real, não Docker local) — não uma medição
  controlada old-code vs new-code no mesmo instante. O benchmark sintético
  abaixo isola a métrica determinística (nº de round-trips) desse ruído.

## Resultado do benchmark

Baseline "antes" recriado só no arquivo de benchmark (as 6 queries
per-tabela removidas de `src/`, fiéis ao texto original, obtidas via
`git show 2e76c87^`) vs. "depois" (`_obter_metadados_schema` real). Nº de
round-trips é determinístico — `queries_depois = 6 × nº de escopos`, nunca
`6 × nº de tabelas`; tempo de parede é informativo (rodar com `-s`),
sujeito à ressalva de piso conservador (Docker local, round-trip
sub-milissegundo):

| tabelas | escopos | queries antes | queries depois | ganho medido |
|--------:|--------:|---------------:|----------------:|-------------:|
|      10 |       4 |             60 |               24 |     1.9x     |
|      50 |       4 |            300 |               24 |     5.6x     |
|     100 |       4 |            600 |               24 |     9.5x     |
|     200 |       4 |           1200 |               24 |    24.3x     |

`queries_depois` fica **fixo em 24** (6 × 4 escopos) independente do nº de
tabelas — é essa razão, não o tempo de parede medido, que sustenta o ganho
estrutural (O(escopos) em vez de O(tabelas)), válida também contra MariaDB
gerenciado real, onde o ganho absoluto de tempo tende a ser maior
(latência de rede por round-trip bem acima do piso de loopback local).
`test_benchmark_colisao_de_constraint_resolvida_corretamente` valida
corretude (não throughput) do cenário de colisão UNIQUE/CHECK dentro do
mesmo lote de volume.

## Banca de revisão pós-implementação (modo somente-leitura)

Antes do PR, o diff completo (`git diff 5a3f948..HEAD`, 4 commits) foi
revisado pela banca completa (arquiteto-de-software, engenheiro-de-dados,
po-revisor) em modo auto, sem permissão de escrita — cada um leu o diff
inteiro, o registry-plan e a issue original; o engenheiro-de-dados validou
empiricamente contra MariaDB 11 real via Docker. **Veredito unânime:
Aprovado, sem bloqueios.**

Achados discutidos com o usuário depois da síntese, com 2 decisões de
ação:

- **`restricoes_fk_compostas_por_tabela` ausente do `_MetadadosDoSchema`**
  (Postgres pré-computa uma vez por schema; MariaDB recomputava a cada
  `extrair_tabela`) — assimetria de design real entre os dois Extratores.
  **Corrigido**: `_obter_metadados_schema` agora pré-computa esse dict
  logo após montar `fks_por_tabela`, mesmo padrão do `ExtratorPostgres`;
  `extrair_tabela` só lê do cache. Sem mudança de comportamento observável
  (535 testes, nenhuma asserção alterada).
- **`extrator_mariadb.py` cresceu de 504 linhas (checkpoint da #80,
  quando o split em subpacote foi avaliado e descartado) para 623**, com
  um eixo de responsabilidade novo (cache/consolidação por escopo) que
  não existia na avaliação da #80. Não é ação desta issue — **registrado
  como issue nova #106** (`refactor: reavaliar split de
  extrator_mariadb.py/extrator_postgres.py em subpacote por
  responsabilidade`), pra banca completa decidir depois, mesmo critério
  já usado nas #80/#96.
- `table_rows`/`reltuples` estimados e cache nunca invalidado durante a
  vida do Extrator: esclarecidos como não-assimetrias/não-riscos novos
  (Postgres já compartilha a mesma característica desde a #66) — sem
  ação.

Issue #105 (`feat: modela múltiplas FK numa mesma coluna, hoje descartada
com Aviso`) também nasceu do teste real pós-implementação (achado de
`member_no`/`ps_partkey`/`ps_suppkey` com múltiplas FK reais na mesma
coluna) — confirmado pela banca como comportamento pré-existente desde a
#56, não regressão desta issue; encaminhamento correto foi issue nova, não
bloqueio.

## Status

Implementado, testado (535 testes unit+integration verdes, mais 2 de
benchmark), revisado pela banca completa (aprovado sem bloqueios) e
documentado. `mypy --strict`/`ruff` limpos. Issues derivadas: #105 (FK
múltipla numa coluna), #106 (reavaliação de split do módulo do Extrator).
Falta abrir o PR pra `development`.

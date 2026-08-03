# Issue #106 — split de `extrator_mariadb.py`/`extrator_postgres.py` em subpacote

## Contexto

A issue #80 avaliou os dois Extratores (504/489 linhas então) e descartou
split: "Adapters extensos porém coesos: SRP já respeitado" — nenhuma razão de
mudança distinta o bastante foi encontrada
(`plan/registry-plan/issue-80-revisao-arquivos-acima-de-300-linhas.md`).

A issue #104 elevou `extrator_mariadb.py` a 634 linhas ao introduzir cache de
metadados por schema (`_MetadadosDoSchema`, `_obter_metadados_schema` +
helpers de agrupamento específicos do MariaDB — UNIQUE composto, JSON via
`CHECK(json_valid(...))`) — um eixo de responsabilidade maior que não existia
na avaliação da #80. A #106 pediu reavaliação, não decisão já tomada.

## Banca de revisão (antes da implementação, exigência da própria issue)

Rodada com arquiteto-de-software, engenheiro-de-dados e po-revisor.

- **1ª proposta avaliada** (espelhando o padrão funcional de `generators/dbt/`
  da #96, candidato citado na própria issue): 3 módulos —
  `_pool.py`/`_metadados_schema.py`/`_construcao.py`, com funções recebendo
  `extrator` como parâmetro explícito.
- **Engenheiro de dados**: risco real em mover pool/cache pra função externa
  preservando a ordem de aquisição de lock aninhado (`_lock_cache_schemas` →
  `_conexao()` → `_lock_pool`/semáforo); recomendou não fragmentar o teste de
  integração desse fluxo.
- **Arquiteto de software**: confirmou que os testes de concorrência que
  cobrem esse aninhamento já existem
  (`test_metadados_de_schema_concorrentes_populam_cache_uma_unica_vez`, nos
  dois Extratores) — mas rejeitou a forma "`função(extrator, ...)`" por
  import circular sem precedente no projeto e por espalhar conhecimento de
  atributos privados de lock por 3 arquivos sem contrato de tipo. Só 2 eixos
  de mudança reais existem (pool/conexão vs. tradução-de-dialeto); cache e
  construção de coluna continuam sendo a mesma responsabilidade, só que mais
  volumosa.
- **PO**: confirmou que nenhuma das funções candidatas ao split é importada
  fora do próprio módulo — zero risco pro wizard CLI ou pra plugins de
  terceiro via `ExtratorRegistrado`. Recomendou não fazer o split simétrico
  no Postgres sem achado próprio de SRP (mesma régua da #80).

**Veredito da banca: split aprovado, escopo mais estreito que o candidato
original** — só `_construcao.py` (funções puras), pool/cache ficam como
métodos na classe principal (evita import circular e preserva a ordem de
lock exatamente como está). PO recomendou aplicar isso só ao MariaDB.

**Decisão do usuário, revisando a recomendação da PO**: fazer o split
simétrico no Postgres também, mesmo com ganho de linhas pequeno — não por
volume, mas por padronização: com só um dos dois Extratores splitado, um 3º
Extrator futuro não teria um padrão único de subpacote pra espelhar. Os dois
Extratores mantêm a mesma forma (`_queries.py` + `mapeamento_de_tipos.py` +
`_construcao.py` + `extrator_x.py`).

## Escopo

- [x] `extractors/mariadb/_construcao.py` (novo) — move verbatim
      `_LinhaColuna`, `_MetadadosDoSchema`, `_construir_coluna`,
      `_promover_booleanos_pela_amostra`, `_quotar_identificador`,
      `_particionar_colunas_unicas`, `_agrupar_colunas_unicas_por_tabela`,
      `_colunas_json_de_check_clauses`, `_agrupar_colunas_json_por_tabela`.
      `extrator_mariadb.py`: 634 → 412 linhas. Pool/cache não tocados.
      `mypy --strict`/`ruff`/`pytest tests/unit/.../mariadb` (52 testes)
      limpos, zero mudança de asserção.
- [x] `extractors/postgres/_construcao.py` (novo) — move verbatim
      `_LinhaColuna`, `_MetadadosDoSchema`, `_construir_coluna`.
      `extrator_postgres.py`: 441 → 376 linhas. Pool/cache não tocados.
      `mypy --strict`/`ruff`/`pytest tests/unit/.../postgres` (45 testes)
      limpos, zero mudança de asserção.
- [x] `mypy --strict src` (92 arquivos) + `ruff check .` + `pytest tests/unit`
      (490 testes) limpos após os dois splits.
- [x] Testes unitários diretos para as funções puras que hoje só têm
      cobertura indireta via `extrair_tabela` (ganho real de granularidade,
      apontado pelo engenheiro-de-dados) — sem fragmentar os testes de
      concorrência/integração da classe inteira, que continuam no mesmo
      arquivo (`test_extrator_mariadb.py`/`test_extrator_postgres.py`).
      Levantamento mostrou que só `_quotar_identificador` (MariaDB) não tinha
      nenhuma cobertura, direta ou indireta — as demais funções já são
      exercitadas de forma realista via `extrair_tabela`, cobrir de novo
      seria duplicar teste sem pegar bug novo. `test_construcao.py` novo em
      `tests/unit/.../mariadb/` cobre o caso de escape de crase. Nenhum gap
      equivalente no lado Postgres (`_construcao.py` de lá só tem
      `_LinhaColuna`/`_MetadadosDoSchema`/`_construir_coluna`, já cobertos).
      492 testes unit, `mypy --strict src`/`ruff` limpos.
- [x] `pytest tests/integration/extractors/{mariadb,postgres}`
      (testcontainers, MariaDB 11 + Postgres 16 reais) — 42 testes verdes, 4
      deselecionados (marcados `benchmark`, fora do escopo padrão). Suítes
      atuais (FK cross-database/composta, promoção BOOLEAN, PK/FK, colisão
      UNIQUE/CHECK) passam sem nenhuma alteração — confirma zero mudança de
      comportamento observável nos dois Extratores.

## Fora de escopo (avaliado)

- Split de pool de conexão (`_obter_pool`/`_conexao`) e cache de metadados
  (`_obter_metadados_schema`) em módulo separado — rejeitado pela banca
  (arquiteto-de-software): import circular sem precedente no projeto, e
  risco de inversão da ordem de aquisição de lock aninhado sem ganho real.
  Ficam como métodos na classe principal dos dois Extratores.

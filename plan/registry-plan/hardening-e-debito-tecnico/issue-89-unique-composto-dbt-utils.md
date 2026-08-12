# Issue #89 — UNIQUE composto estrutural + packages.yml/dbt_utils

Plano completo revisado em `/home/dev/.claude/plans/imperative-tumbling-crescent.md`
(sessão de planejamento). Decisões de design já validadas com o usuário:
`RestricaoUnica` como Value Object (não `list[list[str]]` cru), teste
`dbt_utils.unique_combination_of_columns` com severidade padrão (`error`),
"candidatos relacionados" (intermediate/profiles.yml/analyses/exposures/
freshness/macros) fora de escopo.

- [x] Banca de revisão (arquiteto-de-software + engenheiro-de-dados +
      po-revisor) sobre o plano, antes de qualquer implementação — exigência
      da própria issue #89. Veredito: aprovado com ressalvas pelos 3.
      Achados incorporados ao plano:
      - **Bloqueante (Eng. de Dados, validado contra Postgres 16 real):**
        query Postgres precisa de `indexprs IS NULL` (índice de expressão),
        `k.ord <= indnkeyatts` (índice covering/INCLUDE), `indpred IS NULL`
        (índice parcial/soft-delete) e `indisvalid` — sem isso, a query
        original produziria `RestricaoUnica`/`unica` estruturalmente falsos
        em pelo menos 2 cenários reais.
      - **Bloqueante (Arquiteto de Software):** query MariaDB
        (`_COLUNAS_UNICAS_SQL`) precisa de `ordinal_position` + `ORDER BY`
        — sem isso a ordem das colunas numa constraint composta não é
        estável entre execuções, quebrando o hash estrutural com falsos
        positivos.
      - **Achado (Arquiteto de Software):** `packages.yml` pode ficar órfão
        se o UNIQUE composto for removido depois — `GeradorDbt` precisa
        remover o arquivo explicitamente quando `usa_dbt_utils=False`.
      - **Achado (PO):** documentar em `tasks.md` que
        `GeradorMarkdown`/`GeradorContextoDeIA` ficam fora desta issue,
        apesar de já renderizarem o análogo single-column (`unica`).

## 1. `RestricaoUnica` (Value Object novo)

- [x] `domain/model/common/restricao_unica.py` — `colunas: tuple[str, ...]`,
      `frozen=True`, validator (mínimo 2 colunas, sem duplicata)
- [x] `tests/unit/domain/model/common/test_restricao_unica.py` —
      feliz/erro/borda

## 2. Campo `restricoes_unicas` nos 3 Bounded Contexts

- [x] `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada` ganham
      `restricoes_unicas: list[RestricaoUnica] = Field(default_factory=list)`
- [x] Validator cruzado em `TabelaExtraida`: colunas citadas em cada
      `RestricaoUnica` precisam existir em `self.colunas`
- [x] Confirmar propagação automática via `iniciar_contexto`/`_traduzir`
      (sem mudança de código nesses dois pontos — só teste de regressão)
- [x] Testes de modelo cobrindo o campo novo e o validator cruzado

## 3. `SobrescritaDeTabela._calcular_hash_estrutural`

- [x] Incluir `restricoes_unicas` no hash estrutural
- [x] Teste: mudança de `restricoes_unicas` dispara Aviso de estrutura
      alterada

## 4. `ExtratorPostgres`

- [x] Nova query em `postgres/_queries.py` (substitui
      `_COLUNAS_UNICAS_SCHEMA_SQL` por `_RESTRICOES_UNICAS_SCHEMA_SQL`) via
      `pg_index` + `unnest(...) WITH ORDINALITY`, cobrindo single-column e
      composto numa passada só — incluindo `indexprs IS NULL`,
      `indpred IS NULL`, `indisvalid`, `k.ord <= indnkeyatts` (achados da
      banca)
- [x] `_MetadadosDoSchema.restricoes_unicas_por_tabela` novo
- [x] `_obter_metadados_schema` agrupa por `(tabela, indexrelid)`
- [x] `extrair_tabela` passa `restricoes_unicas` para `TabelaExtraida`
- [x] Atualizar mock de `fetchall.side_effect` existente (só 1 ocorrência
      tinha dado real de UNIQUE — as demais eram `[]`, sem mudança de forma
      necessária)
- [x] Teste novo: UNIQUE composto de 2 colunas vira `RestricaoUnica`, sem
      misturar com índice single-column da mesma tabela (indexrelid distinto)

## 5. `ExtratorMariaDB`

- [x] `_COLUNAS_UNICAS_SQL`: `ORDER BY kcu.constraint_name,
      kcu.ordinal_position` (achado da banca — ordem antes não era
      garantida, quebrava estabilidade do hash estrutural)
- [x] `_colunas_unicas_de_coluna_unica` → `_particionar_colunas_unicas`
      (mesma query `_COLUNAS_UNICAS_SQL`, agora ordenada — só reaproveita o
      agrupamento por `constraint_name` que hoje descarta grupos > 1)
- [x] `extrair_tabela` passa `restricoes_unicas` para `TabelaExtraida`
- [x] `test_unique_composta_nao_marca_nenhuma_coluna_como_unica` ganhou
      asserção de `restricoes_unicas`

## 6. `GeradorDbt`

- [x] `packages.yml` condicional (só quando alguma tabela do lote tem
      `restricoes_unicas`) — `dbt-labs/dbt_utils` `[">=1.0.0", "<2.0.0"]`
- [x] `_model_schema_yaml`/`_testes_de_modelo`: teste model-level
      `dbt_utils.unique_combination_of_columns` por `RestricaoUnica`,
      severidade padrão (sem `config: {severity: warn}`)
- [x] `templates/readme.md.jinja2`: menção a `dbt deps` só quando
      `packages.yml` foi gerado
- [x] Remover `destino/packages.yml` explicitamente quando
      `usa_dbt_utils=False` (achado da banca — evita artefato órfão)
- [x] Testes: `packages.yml` ausente no caminho feliz atual (sem regressão);
      `packages.yml` + teste model-level presentes quando há
      `restricoes_unicas`; artefato órfão removido; `construir_tabela`
      (conftest) estendida com `restricoes_unicas`

## 7. Documentação

- [x] `docs/low_level_design.md` — `TabelaExtraida`/`TabelaCurada`/
      `TabelaAnalisada`, `ExtratorPostgres` (query nova, com os 4
      predicados), `ExtratorMariaDB` (`ORDER BY`), `SobrescritaDeTabela`
      (hash), `GeradorDbt` (`packages.yml` condicional + teste model-level)
- [x] `plan/tasks.md` — reabertura de escopo da #89 na seção 6, incluindo
      nota explícita de que `GeradorMarkdown`/`GeradorContextoDeIA` ficam
      fora desta issue (achado do PO)

## Verificação final

- [x] `mypy --strict` (73 arquivos em `src/`) + `ruff check` (`src` + `tests`)
      — limpos
- [x] `pytest tests/unit` — 421 testes passando, sem regressão em nenhuma
      outra parte do sistema
- [x] Testes de integração (`testcontainers`, Postgres 16 + MariaDB 11
      reais): `restricoes_unicas` correta em UNIQUE composto real (Postgres
      21/21, MariaDB 17/17 passando); tabela `restricoes.indices_especiais`
      nova no Postgres prova contra banco real que índice de expressão,
      covering/`INCLUDE` e parcial (soft-delete) não produzem
      `unica`/`RestricaoUnica` falsos — os 3 bugs bloqueantes achados pela
      banca, agora com regressão automatizada, não só validação manual.
      `indisvalid` (índice inválido) não coberto — simular `CREATE INDEX
      CONCURRENTLY` falho de forma confiável em setup de teste é frágil;
      decisão registrada, não pendência esquecida

# Issue #95 — Classificação categórica em accepted_values + FK composta

Plano completo revisado em `/home/dev/.claude/plans/groovy-humming-axolotl.md` (sessão de
planejamento). Decisões de design já validadas com o usuário: severidade `error` no teste
de FK composta, simetria Markdown/ContextoDeIA incluída nesta mesma issue, teto de
cardinalidade via contagem exata reconstruída de `percentual_unico`, checagem de FK
composta sem PK/UNIQUE correspondente rodando em `OrquestradorParalelo.extrair` (não na
CLI). Detecção de código sequencial disfarçado de categórico (`PRD-N`) avaliada e adiada —
ver apêndice do plano.

- [x] Banca de revisão (arquiteto-de-software + engenheiro-de-dados + po-revisor) sobre o
      plano, antes de qualquer implementação — exigência da própria issue #95 para a Parte
      2. Veredito: aprovado com ressalvas pelos 3. Achados incorporados ao plano:
      - **Bloqueante (PO):** severidade do teste `composite_relationships` — decidido
        `error` pelo usuário, consistente com `unique_combination_of_columns` (#89).
      - **Bloqueante (PO):** simetria Markdown/ContextoDeIA — decidido incluir nesta
        issue (evita o retrabalho #89→#93).
      - **Achado (Engenheiro de Dados):** teto de cardinalidade via `len(valores_frequentes)
        < 10` é ambíguo (não distingue "exatamente 10 distintos" de "200 truncados em
        10") — decidido reconstruir contagem exata via `percentual_unico`.
      - **Achado (Engenheiro de Dados), validado:** semântica `MATCH SIMPLE` (linha com
        qualquer coluna local NULL é excluída da checagem) é o comportamento correto e
        confirmado tanto em Postgres quanto em MariaDB/InnoDB.
      - **Achado (Arquiteto):** comparar tupla via SQL direto, não concatenação de string
        (risco de colisão de delimitador).
      - **Achado (Arquiteto):** `Aviso` explícito quando FK composta aponta pra colunas
        que não formam PK/UNIQUE do lado referenciado — roda em
        `OrquestradorParalelo.extrair` (decisão do usuário), não na CLI.
      - **Achado (Arquiteto):** confirmar antes de nomear a macro que
        `composite_relationships` não colide com convenção de algum pacote community do
        dbt.

## Parte 1 — Falsos positivos em accepted_values / sugestão de filtro enum

- [x] `generators/_metricas.py`: mover/renomear `_TAMANHO_AMOSTRA_MINIMO_ENUM` →
      `_TAMANHO_AMOSTRA_MINIMO_ENUMERACAO`; `_CATEGORIAS_EXCLUIDAS_DE_ENUMERACAO`;
      `_CARDINALIDADE_MAXIMA_ACCEPTED_VALUES = 10`; `_contagem_de_distintos`;
      `_elegivel_para_enumeracao`
- [x] `gerador_dbt.py::_sugestoes_de_teste` usa `_elegivel_para_enumeracao`
- [x] `gerador_contexto_de_ia.py::_sugestao_de_filtro` usa `_elegivel_para_enumeracao`,
      remove constante local
- [x] Testes novos: TIMESTAMP nunca elegível; amostra abaixo do piso (novo pro
      `GeradorDbt`, que não tinha piso antes); exatamente 10 distintos via reconstrução
      não elegível; 9 distintos + amostra ok + cobertura ok elegível — bateria espelhada
      em `test_gerador_dbt.py` e `test_gerador_contexto_de_ia.py` (453 testes unitários
      passando, sem regressão)
- [x] `docs/low_level_design.md` — 5 critérios documentados (`GeradorDbt` e
      `GeradorContextoDeIA`), referência à constante antiga atualizada

## Parte 2 — Modela FK composta (Extraction/Curation/Analysis + dbt + Markdown + IA)

- [x] `RestricaoDeFkComposta` (Value Object novo,
      `domain/model/common/restricao_de_fk_composta.py`) + testes feliz/erro/borda
      (7 testes, mesmo padrão de `RestricaoUnica`)
- [x] `restricoes_fk_compostas` em `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada` +
      validator cruzado (`TabelaExtraida`) + propagação confirmada via
      `iniciar_contexto`/`_traduzir` (nenhum dos dois precisou mudar — testes de
      regressão espelhando o padrão de `restricoes_unicas`/#9)
- [x] `ExtratorPostgres`: `constraint_name`/`ordinal_position` na query de FK + `ORDER BY`;
      helper `construir_restricoes_fk_compostas` (agnóstico de fonte, novo arquivo) +
      testes (helper: 4 testes; Extrator: 1 teste novo de FK composta + 2 testes
      existentes atualizados com constraint_name nas linhas mockadas)
- [x] `ExtratorMariaDB`: `CONSTRAINT_NAME` na query de FK + `ORDER BY`; sem query nova
      além disso — só reagrupamento sobre `_CHAVES_ESTRANGEIRAS_SQL` via o mesmo helper
      compartilhado; testes existentes atualizados + 1 teste novo de FK composta
      (48 testes MariaDB passando, 470 no total — sem regressão)
      - Pendente para a etapa de "Verificação final": testes de integração
        (`testcontainers`, Postgres 16 + MariaDB 11 reais) cobrindo FK composta —
        ainda não escritos, feito ao final da issue junto da verificação completa
- [x] `OrquestradorParalelo.extrair`: `Aviso` quando FK composta não corresponde a
      PK/UNIQUE (single ou composto) do lado referenciado, só quando a tabela
      referenciada está no lote (checagem pós-extração, cross-table);
      `ExtratorFake` (conftest) ganhou `tabelas_customizadas` pra permitir tabelas
      sob medida nos testes; 3 testes novos (sem chave candidata → Aviso; com PK
      composta real → sem Aviso; fora do lote → sem Aviso) — 474 testes no total
- [x] `SobrescritaDeTabela._calcular_hash_estrutural` inclui `restricoes_fk_compostas`
      (mesmo padrão de `restricoes_unicas`/#89) + teste
      `test_hash_muda_quando_fk_composta_e_criada` (471 testes passando)
- [x] `GeradorDbt`: suprime `relationships` per-coluna pra colunas em FK composta; macro
      nova `composite_relationships` (`{% test %}`, comparação via `NOT EXISTS` +
      igualdade por coluna — SQL ANSI puro, sem tupla/ROW nem concatenação;
      `MATCH SIMPLE` via `IS NOT NULL` no CTE `child`; severidade padrão `error`);
      `Aviso` + omissão quando a tabela referenciada está fora do lote; macro
      condicional (órfã removida quando não há mais consumidor, mesmo padrão de
      `unique_percentage_at_least.sql`) — `conftest.py` (generators) ganhou
      `restricoes_fk_compostas` em `construir_tabela`; 5 testes novos
      (479 testes no total, sem regressão)
- [x] `GeradorMarkdown`: bullet "Chaves estrangeiras compostas" em "Fatos extraídos" +
      marcador `"FK (composta)"` por coluna (sem substituir o `"FK → ..."` individual,
      sem suprimir por PK — diferente de UNIQUE composto, não faz sentido aqui), grupos
      ordenados por `colunas_locais`; 3 testes novos (482 testes no total)
- [x] `GeradorContextoDeIA`: `restricoes_fk_compostas` (lista de dicts, diferente de
      `restricoes_unicas` que é lista de listas — carrega 4 campos, não só colunas)
      no JSON por tabela, chave omitida quando vazia, grupos ordenados por
      `colunas_locais`; 2 testes novos (484 testes no total)
- [x] Testes de integração (`testcontainers`, Postgres 16 + MariaDB 11 reais): FK
      composta (2 colunas) pareada corretamente e `RestricaoDeFkComposta` correta
      contra os dois motores — mesma fixture `geografia.pais`/`geografia.filial`
      criada nos dois (nova no MariaDB); `test_listar_escopos_retorna_escopos_semeados`
      (MariaDB) atualizado com o database novo. 42 testes de integração passando
      (extractors), 484 unitários — suíte completa sem regressão.
      - Caso "lado referenciado sem PK/UNIQUE correspondente" (achado do Arquiteto)
        não simulado em integração — já coberto em 3 testes unitários dedicados
        (`test_orquestrador_paralelo.py`); mesmo tratamento dado a `indisvalid` na
        #89 (limitação aceita, registrada, não esquecida)
- [x] `docs/low_level_design.md` — 3 Bounded Contexts (novo Value Object +
      campo), `ExtratorPostgres`/`ExtratorMariaDB` (query + helper),
      `OrquestradorParalelo` (Aviso cross-table), `SobrescritaDeTabela` (hash),
      `GeradorDbt` (supressão + macro `composite_relationships`),
      `GeradorMarkdown`/`GeradorContextoDeIA` (simetria) + `plan/tasks.md`
      (entrada completa das Partes 1 e 2, seção 6)

## Verificação final

- [x] `mypy --strict` + `ruff check` limpos
- [x] `pytest tests/unit` sem regressão (486 testes)
- [x] Testes de integração (Postgres 16 + MariaDB 11 reais) cobrindo FK composta

## Banca de revisão pós-implementação (diff completo, modo auto, somente leitura)

- [x] Convocada a banca completa (arquiteto-de-software, engenheiro-de-dados,
      po-revisor) para revisar o diff final antes do PR. Veredito: Arquiteto
      **aprovado com ressalvas** (nada bloqueante); PO **aprovado** (as 4
      decisões de escopo acordadas verificadas no código, nenhum rastro do
      item adiado de "código sequencial"); Engenheiro de Dados **bloqueante**
      — 2 bugs reais, validados contra Postgres 16 real e por reconstrução
      numérica. Correções abaixo, plano completo em
      `/home/dev/.claude/plans/groovy-humming-axolotl.md`.

- [x] **Bug 1 corrigido:** `_contagem_de_distintos` (`_metricas.py`)
      multiplicava a contagem reconstruída de `percentual_unico` de novo
      pela fração de não-nulos, mas `percentual_unico` já divide pela
      amostra total — subestimava a contagem real sempre que havia nulos
      (ex.: 90% nulos e 60 distintos reais reconstruía como 6), reintroduzindo
      o falso positivo de `accepted_values`/enum que a issue existe para
      eliminar. Fórmula corrigida para `round(tamanho_amostra *
      percentual_unico / 100)`. Testes de regressão espelhados em
      `test_gerador_dbt.py`/`test_gerador_contexto_de_ia.py` (percentual_nulo
      alto cruzando o limiar de 10), validados numericamente antes de
      escrever (fórmula antiga dava 6, corrigida dá 60).

- [x] **Bug 2 corrigido:** `_CHAVES_ESTRANGEIRAS_SCHEMA_SQL` (Postgres) fazia
      JOIN entre `table_constraints`/`key_column_usage` só por
      `constraint_name + table_schema`, sem `table_name` — `constraint_name`
      de FK é único por tabela no Postgres, não por schema, então duas
      tabelas do mesmo schema com FK de mesmo nome (convenção comum tipo
      `fk_parent` repetida) colidiam e a query devolvia o alvo errado.
      Reescrita via `pg_catalog` (`pg_constraint.conrelid`/`confrelid`,
      `unnest(conkey, confkey) WITH ORDINALITY`), mesma técnica de
      `_RESTRICOES_UNICAS_SCHEMA_SQL` (#89). Validado manualmente contra
      Postgres 16 real (container descartável): query antiga produzia 16
      linhas corrompidas/duplicadas no cenário de colisão, nova produz as 4
      corretas. Teste de integração automatizado novo (schema `colisao_fk`,
      `test_extrair_tabela_com_fk_de_nome_colidente_resolve_alvo_correto`).

- [x] **`_CHAVES_PRIMARIAS_SCHEMA_SQL` — tentativa revertida:** cheguei a
      reescrever também via `pg_catalog` por consistência, mas validando
      contra Postgres 16 real descobri que o cenário análogo (colisão de
      nome de PK entre tabelas do mesmo schema) é **impossível de
      reproduzir** — PK nomeada cria índice de apoio, e nomes de índice são
      únicos por schema no Postgres, o motor já impede a colisão
      estruturalmente. Revertido para a query original por decisão do
      usuário, sem carregar uma reescrita sem bug real por trás.

- [x] **Aviso informativo novo (aceito, sugestão do Engenheiro de Dados):**
      `_avisos_de_fk_composta_sem_chave_candidata`
      (`orquestrador_paralelo.py`) ficava em silêncio quando a tabela
      referenciada de uma FK composta está fora do lote — indistinguível de
      "checado e ok". Agora emite um Aviso de teor distinto ("não
      verificada", não "malformada"). Correção cosmética junto: aspas
      simples solta na mensagem do Aviso "sem chave candidata". Teste
      `test_extrair_fk_composta_fora_do_lote_emite_aviso_informativo`
      atualizado (era `..._nao_emite_aviso`).

- [x] Confirmado (não é achado, checagem da banca): `GeradorDbt` **já**
      emitia Aviso informativo (não silêncio) para `relationships`/
      `composite_relationships` fora do lote antes desta correção — não
      havia nada a estender lá, só no `OrquestradorParalelo`.

- [x] Pergunta da banca que fica em aberto, fora do escopo desta correção:
      PO questionou se `severity: error` no `composite_relationships`
      deveria ter opção de configuração exposta ao usuário final — avaliação
      futura de produto, não implementada aqui.

- [x] Suíte final: `mypy --strict` (75 arquivos) + `ruff check src tests`
      limpos; `pytest tests/unit` 486 passados (sem regressão); `pytest
      tests/integration` Postgres 22 passados (1 novo) + MariaDB sem
      alteração.

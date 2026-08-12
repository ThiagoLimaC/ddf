# Issue #96 — organização de módulos para Adapters

Plano completo revisado pela banca (arquiteto-de-software + engenheiro-de-dados)
e pelo usuário em `/home/dev/.claude/plans/composed-sleeping-pie.md` (sessão de
planejamento).

## 1. Split de `generators/gerador_dbt.py`

- [x] `generators/_dbt_templates.py` — carregamento de templates/macros do disco
- [x] `generators/_dbt_sql.py` — cast/render SQL + `_nome_model`
- [x] `generators/_dbt_testes.py` — heurísticas de sugestão de teste (sem separar órfão)
- [x] `generators/_dbt_yaml.py` — montagem de YAML/README
- [x] `generators/gerador_dbt.py` reduzido a orquestração
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` limpos

## 1b. Reorganização em subpasta por Gerador concreto (pedido do usuário,
     ampliação de escopo sobre o checklist original)

- [x] `generators/dbt/` — move os 5 arquivos do item 1 (`_templates.py`,
      `_sql.py`, `_testes.py`, `_yaml.py`, `gerador_dbt.py`), + templates
      Jinja/macros específicos de dbt movidos para `generators/dbt/templates/`
- [x] `generators/markdown/` — split de `gerador_markdown.py` (453 linhas) em
      `_templates.py` (env/filtros registrados) + `_filtros.py` (funções de
      formatação usadas como filtro Jinja) + `gerador_markdown.py`
      (orquestração), templates movidos para `generators/markdown/templates/`
- [x] `generators/contexto_de_ia/` — split de `gerador_contexto_de_ia.py`
      (370 linhas) em `_grafo.py` (grafo de relacionamentos, escopo
      cross-tabela) + `_serializacao.py` (montagem do chunk por tabela,
      escopo single-tabela) + `gerador_contexto_de_ia.py` (orquestração)
- [x] `pyproject.toml` — 3 entry points de `ddf.geradores` atualizados
- [x] Testes movidos para espelhar a nova estrutura
      (`tests/unit/.../generators/dbt|markdown|contexto_de_ia/`)
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` limpos após
      cada Gerador

## 2. `extractors/comum/` + `extractors/estrategias/`

- [x] `extractors/comum/` — construir_metadados_de_amostra, seed_efetivo,
      construir_colunas_fk, construir_restricoes_fk_compostas
- [x] `extractors/estrategias/` — percentual_de_linhas, tabela_inteira
      (nome em português, revisão do usuário sobre a hipótese inicial em
      inglês — "sampling")
- [x] Imports atualizados em extratores concretos, `cli/registro/estrategias.py`,
      testes unit e integration, `conftest.py` de `extractors/`
- [x] `docs/engineer_guidelines.md` (linha ~360-365) atualizado

## 3. `generators/comum/` + `analyzers/comum/`

- [x] `generators/comum/` — `_escrita.py`, `_metricas.py`
- [x] `analyzers/comum/` — `detector_de_formato.py` (proativo, 1 consumidor hoje)
- [x] Imports atualizados

## 4. Organização de testes por categoria — suíte inteira (`tests/unit/`)

**Revisado após protótipo avaliado pelo usuário** (`test_resultado.py`):
split físico em 3 arquivos por módulo ficou fragmentado demais ("quem
procura teste, procura teste por arquivo"). Formato final: **classes por
categoria dentro do mesmo arquivo** — `class TestFeliz`/`class
TestErro`/`class TestBorda`, métodos de teste dentro de cada uma
(`self` como primeiro parâmetro, fixtures via parâmetro normalmente).
Docstring da classe carrega o rótulo da categoria ("Caminho feliz.",
"Erro esperado.", "Bordas."); docstring do método descreve só o
comportamento específico, sem repetir o rótulo. `pytest -v` já mostra o
agrupamento via `TestFeliz::`/`TestErro::`/`TestBorda::` nos IDs de teste.
Categoria sem teste aplicável simplesmente não vira classe.

- [x] `tests/unit/domain/shared/test_resultado.py` — protótipo aprovado
- [x] Aplicar em todo `tests/unit/domain/` (script `split_test_classes.py`
      via ast + `ruff format`/`ruff check --fix`, ver nota abaixo)
- [x] Aplicar em todo `tests/unit/pipeline/`
- [x] Aplicar em todo `tests/unit/infrastructure/` (31 arquivos)
- [x] Helpers locais (`_schema_yml`, `_tabela_com_colunas` etc.) ficam no
      próprio arquivo, fora das classes — decisão revisada: como não há
      mais split físico em 3 arquivos, promover para `conftest.py` deixou
      de ser necessário pra evitar duplicação
- [x] Commit por camada (domain, pipeline, infrastructure), não por módulo

**Nota de execução:** a partir do 3º arquivo (`test_extraction.py`), o
trabalho mecânico (agrupar por categoria via docstring/comentário
existente, adicionar `self`, indentar sob a classe) passou a ser feito por
um script Python usando `ast` (não regex ingênuo — tentativa inicial por
regex quebrou docstring multi-linha e deixou comentário de marcador
duplicado), seguido de `ruff format` + `ruff check --fix` pra normalizar
quebra de linha/indentação. Validado arquivo a arquivo: contagem de teste
antes/depois idêntica, `pytest`/`mypy --strict`/`ruff check` limpos.

**Achado à parte (não é escopo da issue, mas quebrou 2 testes de
integração):** mover os 3 Geradores para subpacote (`generators/dbt/`
etc.) mudou os caminhos nos entry points de `pyproject.toml`, mas a
instalação editável (`.venv/.../ddf-0.1.0.dist-info/entry_points.txt`)
ficou com o metadado antigo cacheado — `uv pip install -e .` de novo
resolve. Sintoma: `test_entry_points_nativos_resolvem_sem_avisos` e
`test_wizard_fluxo_completo_com_extrator_fake` (ambos em
`tests/integration/cli/`) falhando com `ModuleNotFoundError` apontando
pro caminho antigo do Gerador.

## 5. Docstring por conteúdo — `src/ddf/` inteiro

**Critério revisado pelo usuário após a primeira passada:** o critério
inicial ("a referência de issue explica decisão técnica real ou só aponta o
PR?") estava errado — mesmo quando a issue carrega contexto técnico real,
esse conteúdo não pertence à docstring, pertence ao histórico do projeto
(`plan/registry-plan/`, commit message, `git blame`). Docstring existe só
pra descrever o **comportamento atual** do código — nunca proveniência,
história de decisão ou menção a implementação já substituída. Ver memória
`feedback_docstring_sem_referencia_a_issue`.

- [x] Levantadas as 53 ocorrências de `#NN`/`issue #NN` em `src/ddf/`
      (`grep -rn`, 19 arquivos — a contagem de 49/18 da primeira passada
      estava porque `cli/registro/analisadores.py` só citava "issue #67" em
      prosa, sem `#`, e não tinha entrado no grep original)
- [x] Todas as 53 ocorrências removidas — cada uma reescrita descrevendo só
      o comportamento/motivo técnico atual, sem número de issue, sem
      "achado da banca", sem "decisão do usuário", sem apontar implementação
      anterior substituída
- [x] Revisão linha a linha de `postgres/_queries.py`/`mariadb/_queries.py`
      (achado de risco da banca) — conteúdo técnico de cada comentário
      preservado (semântica de `relkind`/`n_live_tup`, predicados de índice
      único, `unnest(conkey, confkey)`), só a referência de issue removida
- [x] Docstring de `generators/dbt/gerador_dbt.py` e
      `generators/contexto_de_ia/gerador_contexto_de_ia.py` corrigida de
      quebra: citavam nomes de módulo antigos (`_dbt_sql.py` etc.) da época
      pré-1b, já desatualizados independente da questão de issue
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` (486
      testes) limpos

**Segunda rodada — docstring enorme vs. duplicação/lacuna de documentação
de design** (pedido do usuário, distinto da limpeza de issue acima):
levantamento via `ast` das docstrings mais longas de `src/ddf/` + auditoria
pelo arquiteto-de-software cruzando cada uma contra
`docs/low_level_design.md`/`system_design_doc.md`.

- [x] Achado principal: `generators/dbt/_testes.py::_sugestoes_de_teste`
      tinha 60 linhas de docstring (quase o dobro do 2º maior do projeto),
      reexplicando 3 blocos já documentados em `low_level_design.md`
      (critérios de `_elegivel_para_enumeracao`, dispatch `matches_format`,
      thresholds soft) — reduzida a ~13 linhas + ponteiro pro design doc
- [x] Mesmo padrão de duplicação corrigido em
      `generators/contexto_de_ia/_grafo.py::_montar_grafo` e
      `generators/dbt/_yaml.py::_testes_de_modelo` (menor escala)
- [x] Lacuna oposta identificada e corrigida: conhecimento de design real
      que só existia cravado no código, nunca promovido pra
      `docs/low_level_design.md` — adicionado:
      - Seção "Mapeamento de tipos MariaDB" (tabela de tipos + detecção de
        coluna JSON via `CHECK(json_valid(...))` + promoção
        `TINYINT(1)`→`BOOLEAN` pela amostra), MariaDB não tinha equivalente
        à tabela que `ExtratorPostgres` já tinha
      - Parágrafo de normalização de dtype não-nativo
        (`pl.Object`/`pl.List`/binário) em `AnalisadorDeMetricasDeColuna` —
        o incidente que motivou isso já estava na Decisão 12 do
        `system_design_doc.md`, mas a correção estrutural nunca tinha sido
        documentada
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` (486
      testes) limpos após os cortes de código

## 6. `docs/engineer_guidelines.md`

- [x] Regra "Docstring descreve comportamento atual, nunca histórico" +
      exemplo positivo/negativo, na seção de Docstrings — inclui a
      sub-regra "docstring longa não é proibida, mas duplicar `docs/` é"
      (resumo de uma linha + ponteiro se já documentado; promover pra
      `low_level_design.md` se for conhecimento de design não documentado)
- [x] Convenção `TestFeliz`/`TestErro`/`TestBorda` documentada na seção
      "Política de testes" (classes por categoria dentro do mesmo arquivo,
      com exemplo real do padrão já em uso em `tests/unit/`)
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` (486
      testes) limpos
- [x] ~~Menção a `percentual_de_linhas.py` atualizada para
      `extractors/sampling/`~~ — bullet desatualizado: essa atualização já
      foi feita no item 2/3, e usou `extractors/estrategias/` (português),
      não `sampling/`. Nada pendente aqui.

## 7. Nota para issue futura — performance de extração

Discussão levantada pelo usuário fora do escopo da #96 (organização de
módulo), avaliada pela banca (arquiteto-de-software + engenheiro-de-dados) e
validada empiricamente antes de virar nota. **Conclusão: não há caso hoje
para processamento distribuído (Spark/Ray/Celery) — os dois gargalos reais
medidos vivem dentro do SGBD/rede, não em volume de dado no cliente.**

- [x] Assimetria Postgres (cache por schema, issue #66) vs MariaDB (6
      queries de catálogo por tabela, sem cache) confirmada como gargalo
      dominante em carga de muitas tabelas pequenas/vazias — evidência
      empírica: extração real de 845 tabelas MariaDB (a maioria vazia) levou
      364s com `max_trabalhadores=8` (~431ms/tabela em média, ~3,4s por
      rodada de 8) — tempo incompatível com "nada para processar", aponta
      pra overhead de round-trip de catálogo. **Candidata a issue futura:**
      replicar no `ExtratorMariaDB` o padrão já usado no Postgres (#66) —
      consolidar as 6 queries por tabela em queries por schema, cacheadas.
- [x] Custo de amostragem (`PercentualDeLinhas`, `WHERE RAND() <= p`) em
      tabela grande medido contra dado real — `TalkingData.app_events`
      (32,4M linhas, MariaDB público em `relational.fel.cvut.cz`):
      `SELECT COUNT(*) WHERE RAND() <= 0.01` levou 22,27s, **inteiramente
      dentro do banco** (full scan avaliando `RAND()` linha a linha, antes
      de qualquer linha trafegar pro cliente). Confirma que mesmo em tabela
      de dezenas de milhões de linhas, o `Extrator` nunca materializa o
      volume bruto — só recebe a amostra já filtrada pelo SGBD (~325 mil
      linhas nesse caso), que cabe folgadamente em Polars local. Um
      `OrquestradorDistribuido`/Spark não atacaria esse custo — ele está no
      plano de execução do MariaDB, não em processamento pós-scan no
      cliente. **Candidata a issue futura (menor prioridade, sem caso real
      urgente):** revisar a estratégia de amostragem pra evitar full scan em
      tabelas muito grandes no MariaDB (ex.: amostra por faixa de PK em vez
      de `RAND()` sobre a tabela inteira) — trade-off já documentado no
      docstring de `PercentualDeLinhas`.
- [x] Registrado explicitamente: `OrquestradorDeTabelas` como Port já é
      neutro o bastante pra permitir uma implementação alternativa de
      paralelismo (`system_design_doc.md` já nomeia Ray/Celery como
      candidatos corretos de categoria — task parallelism sobre chamadas de
      rede independentes, não data parallelism sobre dataframe distribuído
      como o Spark). Não há gatilho de produto hoje pra essa extensão — fica
      só como ponto de extensão já previsto pela arquitetura, não como
      trabalho a fazer.

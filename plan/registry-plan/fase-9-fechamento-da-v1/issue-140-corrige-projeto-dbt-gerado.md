# Issue #140 — fix: corrige o projeto dbt gerado para rodar contra Postgres e MariaDB

## Contexto

Auditoria completa e definitiva do estado atual de `src/ddf/`+`tests/` contra
o que `CLAUDE.md`/`docs/*` prometem, feita ao final da v1 — não um diff, o
pacote inteiro. Todos os achados abaixo foram validados empiricamente contra
Postgres 15/16 e MariaDB 11.8 reais (containers descartáveis) ou executando os
próprios Geradores contra fixtures reais, não por leitura estática de código.

O `GeradorDbt` produz o artefato central do pitch do PRD ("projeto dbt
rodável"). Os achados aqui atingem diretamente isso: o projeto gerado hoje não
roda em cenários comuns de banco real, para os dois motores suportados.

## Decisões tomadas na discussão prévia (antes de implementar)

> **MariaDB como destino de "projeto dbt pronto para rodar" é promessa real
> da v1 — confirmado com o usuário, sem ambiguidade.** Não é nota de escopo
> a ser documentada como limitação: exige correção completa, simétrica ao
> tratamento já dado a Postgres.

> **`unique`/`not_null` amostral ganha o mesmo piso+`severity: warn` dos
> demais testes soft — decisão do usuário, não a alternativa de restringir a
> inferência amostral só a `AmostragemIntegral`** (que seria estatisticamente
> mais limpa — zero falso-positivo por natureza, em vez de só reduzir a taxa
> — mas o usuário preferiu manter a mesma política já usada pelos outros
> testes soft, para não introduzir uma segunda regra). Pedido explícito do
> usuário: documentar no artefato gerado a probabilidade real de
> falso-positivo por trás da inferência amostral, para quem consome o
> `schema.yml` entender o risco antes de rodar `dbt test` contra produção.

## Achados desta issue, com evidência

### 1. CAST hardcoded em dialeto Postgres/ANSI — quebra em MariaDB real

**Arquivo:** `src/ddf/infrastructure/adapters/generators/dbt/_sql.py:30-91`
(`_tipo_sql`, `_expressao_coluna`)

`_tipo_sql` emite tipo ANSI/Postgres fixo, sem nenhum dispatch por motor.
Validado contra **MariaDB 11.8.8 real**:

| CAST gerado | MariaDB 11.8 |
|---|---|
| `CAST(x AS BIGINT)` | `ERROR 1064` (syntax) |
| `CAST(x AS TEXT)` | `ERROR 1064` |
| `CAST(x AS NUMERIC(10,2))` | `ERROR 1064` |
| `CAST(x AS TIMESTAMP)` | `ERROR 1064` |
| `CAST(x AS BOOLEAN)` | `ERROR 1064` |
| `CAST(x AS JSON)` | `ERROR 1064` |
| `CAST(x AS DOUBLE PRECISION)` | `ERROR 1064` |
| `CAST(x AS INTEGER)` / `VARCHAR(n)` / `DATE` / `TIME` | ok |

Qualquer tabela MariaDB com uma coluna `bigint`, `decimal`, `text`,
`datetime`, `tinyint(1)` ou `double` — ou seja, praticamente toda tabela real
— gera um model que quebra `dbt run` na primeira linha. `docs/low_level_design.md:2207-2212`
afirma que os tipos usados são "equivalente ANSI portável" — essa premissa
está incorreta para MySQL/MariaDB, que nunca aceitou esses nomes de tipo em
`CAST`.

**Complicador estrutural:** nenhum modelo de domínio carrega a identidade do
motor de origem (`BancoAnalisado`/`TabelaAnalisada` não têm campo
`motor`/`dialeto`) — o `GeradorDbt` não tem, hoje, como saber que o lote veio
de MariaDB.

**Caminho de correção recomendado:** em vez de adicionar identidade de motor
ao domínio (mudança de modelo, tocaria Extraction→Analysis), usar as macros
cross-database que o próprio dbt-core já resolve em runtime
(`dbt.type_bigint()`, `dbt.type_string()`, `dbt.type_timestamp()`, ou
`api.Column.translate_type(...)`) em vez de literais de tipo — o dbt decide o
dialeto certo sozinho, sem o `ddf` precisar saber a origem. Mais barato e não
toca hexágono. Se, na implementação, alguma macro cross-database não cobrir um
caso (ex.: `ENUM`/`SET` do MariaDB, que hoje já caem em passthrough sem CAST),
documentar a exceção explicitamente — não é motivo para adicionar identidade
de motor ao domínio por si só.

### 2. Identificadores nunca são quotados

**Arquivos:** `generators/dbt/_sql.py:89-91` (CAST), `generators/dbt/_yaml.py:37`
(`schema.yml`), geração de `_nome_model`

Executando o `GeradorDbt` real com uma tabela contendo as colunas `order` e
`Nome Completo`, o artefato sai:

```sql
    CAST(order AS INTEGER) as order,
    CAST(Nome Completo AS VARCHAR(50)) as Nome Completo
```

Validado contra Postgres 15 real: `ERROR: syntax error at or near "Completo"`.
Idem para `order` (palavra reservada) nos dois motores. O mesmo nome cru vai
para `schema.yml` (`- name: Nome Completo`). `_nome_model` monta
`stg_{escopo}__{tabela}` sem sanitização — um schema `sales-eu` ou tabela
`order-items` produz nome de model que o dbt não aceita como identificador.

Cenário real: schema criado por ORM (.NET/EF, Hibernate) gera colunas
`"CreatedAt"`, `"UserId"`; colunas `order`, `rank`, `key`, `desc` são triviais
de encontrar em MySQL legado.

**Correção:** quotar identificadores de forma consistente (aspas duplas ANSI,
que os dois motores aceitam) em todo lugar que hoje interpola nome cru —
`_sql.py`, `_yaml.py` — e sanitizar/validar a geração do nome do model.

### 3. `unique`/`not_null` com `severity: error` derivados só de amostra, sem piso

**Arquivo:** `generators/dbt/_testes.py:149-160`

```python
unico = coluna.unica or (tamanho_amostra > 0 and metrica.percentual_unico == 100.0)
nao_nulo = coluna.nao_nulavel or (tamanho_amostra > 0 and metrica.percentual_nulo == 0.0)
```

A #44/#14 registraram esse viés e `low_level_design.md:2032-2036` declara
resolvido — mas é um `or`, não um `and`: o caminho puramente amostral continua
ativo, e é o **único** teste amostral do arquivo sem piso de amostra e sem
`severity: warn` (`accepted_values`/`not_null_proportion`/
`unique_percentage_at_least` têm ambos).

**Quantificado:** tabela de 5M linhas com 5 pares duplicados de e-mail,
amostragem Bernoulli 10% (default do wizard): P(algum par cai inteiro na
amostra) = 1−(1−0,01)^5 ≈ **4,9%**. Ou seja, em ~95% das execuções o `ddf`
afirma "100% único" e escreve um teste `unique` de `severity: error` que
falha no primeiro `dbt test` contra a tabela completa. Para `not_null`: 5
nulos em 5M linhas, 10% de amostra → P(nenhum na amostra) = 0,9^5 ≈ **59%**.

O README gerado (`templates/readme.md.jinja2`) já explica ao usuário que
testes amostrais são `warn` "porque são calculados sobre uma amostra" — e
lista `accepted_values`, `matches_format`, `not_null_proportion`,
`unique_percentage_at_least`, **sem mencionar `unique`/`not_null`**, que são
amostrais também. O artefato documenta uma política que o código não cumpre.

O caso em que a inferência amostral **é** válida — `AmostragemIntegral`/
`TabelaInteira`, onde a amostra é a população — existe e é distinguível
(`TabelaAnalisada.metadados_amostra.estrategia`), mas `_sugestoes_de_teste`
só recebe `tamanho_amostra`.

**Correção (decisão já fechada, ver acima):** aplicar o mesmo piso
(`_TAMANHO_AMOSTRA_MINIMO_SOFT`) + `severity: warn` ao ramo amostral de
`unique`/`not_null` — mesma política dos demais testes soft, sem restringir a
`AmostragemIntegral`. Atualizar o README gerado para: (a) listar
`unique`/`not_null` entre os testes que podem vir de amostra, e (b) explicar
em termos concretos (com um exemplo numérico, tipo o cálculo acima) a
probabilidade de falso-positivo — não só "é calculado sobre uma amostra"
genérico.

### 4. FK composta faz a coluna perder `relationships` legítimo em silêncio

**Arquivos:** `extractors/comum/construir_colunas_fk.py:30-43`,
`generators/dbt/_testes.py:191-216`, `domain/model/analysis.py:60-69`

Montado o schema multi-tenant canônico em Postgres real
(`tenants(id PK)`, `users(tenant_id,id PK)`,
`orders(tenant_id → tenants.id, FK(tenant_id,user_id) → users(tenant_id,id))`)
e rodado `ExtratorPostgres` + Analisador + `GeradorDbt` reais:

```
orders.tenant_id  fk=True  refs=[('tenants','id'), ('users','tenant_id')]
restricoes_fk_compostas=[(tenant_id,user_id) → users(tenant_id,id)]
schema.yml → tenant_id: tests: [unique, not_null]   ← nenhum relationships, nenhum Aviso
```

`tenant_id` tem uma FK single-column **legítima** para `tenants`, que nunca
vira `relationships`, porque o guard `coluna.nome not in
colunas_em_fk_composta` mata os dois ramos do `if/elif` — e `contadores` só é
incrementado dentro dos ramos, então **nem Aviso sai**. O usuário perde
silenciosamente um teste de integridade real. Também afeta Markdown/
`ai_context.json`, que renderizam `tenant_id` como se tivesse duas
referências independentes (a segunda só existe no par composto).

Adicional: docstring de `ColunaAnalisada.referencias` (`analysis.py:64-68`)
afirma que FK composta "não aparece aqui" — empiricamente aparece, decomposta
por coluna; `low_level_design.md:278-287` diz o contrário (correto). O código
segue o LLD; o docstring está desatualizado e precisa ser corrigido junto.

**Correção:** ajustar o guard em `_testes.py` para só suprimir `relationships`
quando a coluna **não** tem nenhuma referência single-column própria fora da
FK composta — emitindo `Aviso` quando de fato suprimir (não silêncio).
Corrigir o docstring de `ColunaAnalisada.referencias`.

### 5. Nenhum teste executa `dbt parse`/`dbt compile` sobre o artefato gerado

**Arquivo:** `tests/unit/.../generators/dbt/test_gerador_dbt.py` (1604 linhas)

Todas as 1604 linhas de teste do `GeradorDbt` afirmam sobre strings que o
próprio Gerador produziu — asserção de forma, nunca de executabilidade. É
exatamente a razão dos achados 1-3 acima terem sobrevivido a #14, #77, #89,
#90, #95 e três bancas de revisão anteriores: a categoria "caminho feliz" está
formalmente coberta, mas a pergunta que o teste deveria responder ("que bug
real isso pegaria?") nunca incluiu a única propriedade que o PRD vende —
*rodar*.

**Correção:** adicionar `dbt-core` (mais o adapter `dbt-postgres`/
`dbt-mysql` ou equivalente MariaDB-compatível) como dependência de dev, e
rodar `dbt parse`/`dbt compile` sobre o projeto gerado nos testes de
integração já existentes (Postgres 16 + MariaDB 11 via testcontainers) —
incluindo fixtures com os tipos/identificadores que hoje quebram (achados 1 e
2 acima).

## Escopo desta issue

- [ ] `generators/dbt/_sql.py` — `_tipo_sql`/`_expressao_coluna` via macros
      cross-database do dbt-core, sem literal de tipo fixo
- [ ] `generators/dbt/_sql.py`/`_yaml.py` — quoting consistente de
      identificadores (coluna, tabela, nome de model); sanitização/validação
      do nome do model gerado
- [ ] `generators/dbt/_testes.py` — piso de amostra + `severity: warn` no
      ramo amostral de `unique`/`not_null`
- [ ] `generators/dbt/templates/readme.md.jinja2` — `unique`/`not_null`
      entram na lista de testes potencialmente amostrais; explicação
      concreta (com exemplo numérico) da probabilidade de falso-positivo
- [ ] `extractors/comum/construir_colunas_fk.py`/`generators/dbt/_testes.py`
      — guard de supressão de `relationships` corrigido para FK composta +
      single-column própria; `Aviso` emitido quando de fato suprimir
- [ ] `domain/model/analysis.py` — corrigir docstring de
      `ColunaAnalisada.referencias`
- [ ] `docs/low_level_design.md:2207-2212` — corrigir afirmação de "ANSI
      portável"
- [ ] `pyproject.toml` — `dbt-core` + adapter(s) necessário(s) como
      dependência de dev
- [ ] `mypy --strict`/`ruff` limpos

## Testes

- [ ] `dbt parse`/`dbt compile` sobre o projeto gerado, em teste de
      integração, contra Postgres **e** MariaDB (testcontainers), incluindo
      fixture com tipos citados no achado 1 (BIGINT/TEXT/NUMERIC/TIMESTAMP/
      BOOLEAN/JSON/DOUBLE) e identificadores citados no achado 2 (palavra
      reservada, espaço, hífen no nome do schema)
- [ ] Unit: teste novo reproduzindo o cenário numérico de falso-positivo de
      `unique`/`not_null` amostral (5 duplicatas/5M linhas análogo, ou
      equivalente proporcional testável), confirmando piso+`warn` aplicados
- [ ] Unit: coluna com FK composta + FK single-column própria válida —
      `relationships` da FK simples presente, sem supressão indevida
- [ ] Unit: coluna só em FK composta (sem FK própria) — `relationships`
      suprimido, `Aviso` emitido (não silêncio)
- [ ] Regressão: suíte completa de `test_gerador_dbt.py` segue verde após as
      mudanças de CAST/quoting (ajustar asserções de string existentes que
      hoje esperam o CAST antigo sem macro/quoting)

## Verificação final

- [ ] `mypy --strict src` + `ruff check .` limpos
- [ ] `pytest tests/unit` + `pytest tests/integration` (Postgres+MariaDB
      reais) verdes
- [ ] `dbt parse` manual contra um projeto gerado real (Postgres e MariaDB),
      confirmando que os dois compilam sem erro

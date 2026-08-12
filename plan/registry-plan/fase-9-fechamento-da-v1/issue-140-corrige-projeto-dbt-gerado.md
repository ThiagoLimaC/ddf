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

Plano completo revisado em `/home/dev/.claude/plans/swift-snuggling-anchor.md`
(sessão de planejamento). Banca de revisão (arquiteto-de-software +
engenheiro-de-dados + po-revisor) rodada sobre o plano antes da
implementação — achados incorporados ao plano antes do código.

- [x] `generators/dbt/_sql.py` — `_tipo_sql`/`_expressao_coluna` via macro
      de dispatch por adapter próprio (`cast_type`, mesmo padrão de
      `matches_format`/#90), **não** os macros builtin do dbt-core
      recomendados originalmente pela issue.
  - Decisão técnica: verificado contra o código-fonte real do dbt-core e do
    adapter MariaDB (`dbt-mysql`) que os macros builtin (`dbt.type_bigint()`
    etc.) não resolvem o problema — o adapter só sobrescreve
    `type_timestamp()`; os demais caem no default do dbt-core, que devolve
    nomes que o `CAST()` real do MariaDB rejeita, e `type_numeric()`
    descarta a precisão/escala real da coluna. Tabela de dispatch validada
    empiricamente contra Postgres 15/MariaDB 11.8 reais pelo engenheiro de
    dados (`SIGNED`, `CHAR`, `DECIMAL(p,s)`, `DATETIME(n)`, `UNSIGNED`,
    `DOUBLE`, `FLOAT`).
  - `NUMERIC`/`DECIMAL` sem precisão/escala: roteado pelo mesmo dispatch
    (`tipo_canonico='NUMERIC'`) — Postgres repassa (seguro, precisão
    arbitrária), MariaDB falha explícito no `dbt compile`
    (`raise_compiler_error`), não na geração do `ddf` (que não conhece o
    motor de destino). 
  - `VARCHAR` sem tamanho e `ENUM`/`SET` (sem equivalente ANSI) passam a
    convergir para o mesmo canônico `TEXT` de um `TEXT` nativo — mesmo
    risco de CAST, achado durante a implementação, fora da tabela original
    do plano.
  - `TIMESTAMP`/`TIME` sempre passam pelo dispatch agora (não só quando
    `WITH TIME ZONE`), carregando `precisao_fracionaria` real — escopo
    expandido nesta sessão (ver item de captura de `datetime_precision`
    abaixo).
  - `_precisa_cast_type` implementado em `_sql.py` (não `_testes.py` como o
    plano inicial sugeria — mais coeso com `_CATEGORIAS_DISPATCHADAS`, que
    já mora ali), macro condicional/órfão no mesmo padrão dos demais.
- [x] Reabertura de escopo desta própria issue, decidida com o usuário
      durante a implementação: captura de `datetime_precision` do catálogo
      nos dois extratores (Postgres e MariaDB) — achado da auditoria
      pontual do engenheiro de dados sobre `mariadb/mapeamento_de_tipos.py`
      (gap encontrado ao investigar por que `DATETIME(6)` estava hardcoded
      no macro `cast_type`).
  - `TipoDeDado.precisao_fracionaria: int | None` novo, permitido só para
    TIMESTAMP/TIME (mesmo padrão de `com_timezone`).
  - `_queries.py`/`_LinhaColuna`/`_construir_coluna`/`mapeamento_de_tipos.py`
    dos dois motores propagam `datetime_precision` real; MariaDB ganhou
    branch próprio pra `time` (antes agrupado em `_CATEGORIAS_SIMPLES`,
    sem lugar pra carregar a precisão).
  - Gap de tipos `YEAR`/`BINARY`/`VARBINARY`/`BLOB`/`BIT` caindo em
    `UNKNOWN` no MariaDB (achado da mesma auditoria) **não** entrou nesta
    issue — registrado como candidato a issue futura, sem relação direta
    com o CAST corrigido aqui.
- [x] `generators/dbt/_sql.py` — quoting via `{{ adapter.quote() }}` builtin
      do dbt-core (não aspas duplas fixas — validado que não funcionam no
      MariaDB sem `ANSI_QUOTES`, achado do engenheiro de dados); aplicado
      em toda referência de coluna no SQL gerado (CAST, argumento do
      dispatch `cast_type`, passthrough) **e** no alias (`as <coluna>`),
      que quebra do mesmo jeito com nome reservado sem aspas — achado
      durante a implementação, fora do plano original.
  - Nomes com apóstrofo escapados no literal Jinja (`d'agua` →
    `adapter.quote('d\'agua')`).
- [x] `generators/dbt/_sql.py`/`gerador_dbt.py` — nome de model inválido
      (`_nome_model_invalido`/`_tabela_com_nome_model_invalido`) vira
      `Falha` explícita em `GeradorDbt.__call__`, verificada antes de
      qualquer escrita em disco — decisão do usuário (não normalização
      silenciosa), alinhada a RNF1/RNF4 do PRD. `_yaml.py` não precisou de
      mudança: `schema.yml`/`sources.yml` usam `name:` cru, dbt resolve
      quoting internamente nesses arquivos.
- [x] `generators/dbt/_testes.py` — piso de amostra
      (`_TAMANHO_AMOSTRA_MINIMO_SOFT`) + `severity: warn` no ramo amostral
      de `unique`/`not_null`; fato estrutural do schema (`coluna.unica`/
      `nao_nulavel`) continua prioritário e gera `severity: error` (padrão
      do dbt), nunca os dois ao mesmo tempo.
  - Achado do engenheiro de dados, incorporado ao README: diferente dos
    testes soft de faixa (10%/95%, com margem estatística), `unique`/
    `not_null` afirmam valor **extremo** (0%/100%), sem margem — o piso
    não reduz a taxa de falso-positivo do mesmo jeito; a proteção real
    vem inteiramente do `severity: warn`.
- [x] `generators/dbt/templates/readme.md.jinja2` — `unique`/`not_null`
      entram na lista de testes potencialmente amostrais; exemplo numérico
      concreto (P(falso positivo) por amostra Bernoulli, ~95%/~59% no
      cenário de 5M linhas/10% de amostra) + nota de que o piso não protege
      esse par do mesmo jeito que protege os testes de faixa.
- [x] `generators/dbt/_testes.py` — guard de supressão de `relationships`
      corrigido para FK composta + single-column própria; `Aviso` emitido
      só quando de fato suprimir.
  - `construir_colunas_fk.py` não precisou de mudança — confirmado por
    leitura que a mesma linha bruta de FK já alimenta tanto ele quanto
    `construir_restricoes_fk_compostas`, sem filtro entre os dois; o bug
    era só no consumo (`_sugestoes_de_teste`), não na extração.
  - `_referencias_de_fk_composta` novo (`_testes.py`) — filtra
    `coluna.referencias` por posição contra `RestricaoDeFkComposta.
    colunas_locais`/`colunas_referenciadas`, em vez de suprimir a coluna
    inteira via `set[str]` de nomes.
  - Mudança de assinatura confirmada pelo arquiteto na revisão de plano:
    `_sugestoes_de_teste`/`_coluna_schema_yaml`/`_model_schema_yaml`
    (`_yaml.py`) trocam `colunas_em_fk_composta: set[str]` por
    `restricoes_fk_compostas: list[RestricaoDeFkComposta]`.
- [x] `domain/model/analysis.py` — corrigido docstring de
      `ColunaAnalisada.referencias` (afirmava que FK composta "não aparece
      aqui"; empiricamente aparece, decomposta por coluna, junto de
      qualquer FK single-column própria).
- [x] `docs/low_level_design.md:2207-2212` (CAST SQL) e `:105-106`
      (ENUM/SET) — corrigida a afirmação de "ANSI portável"; documentado o
      dispatch `cast_type` por adapter e a convergência VARCHAR-sem-tamanho/
      ENUM/SET/TEXT pro mesmo canônico `TEXT`.
- [x] `pyproject.toml` — `dbt-core`+`dbt-postgres` (modernos, 1.12.1/1.11.0)
      como dependência de dev normal.
  - **Achado real durante a implementação, não coberto pelo plano:**
    `dbt-mysql` (único adapter dbt com `type: mariadb`) trava em
    `dbt-core<=1.7.19`, que **não roda em Python 3.12** (mínimo do
    projeto) — e mesmo fixando a versão exata, `dbt-core<=1.7` exige
    `pathspec<0.12`, incompatível com `mypy>=2.1.0` (`pathspec>=1.0.0`)
    já usado pelo projeto. Não é um conflito resolvível por pinning.
    Decisão do usuário: `dbt-mysql` nunca entra na dependência de dev
    normal — o teste de integração do lado MariaDB provisiona (e
    cacheia) um venv Python 3.11 isolado sob demanda
    (`tests/integration/generators/dbt/conftest.py::dbt_mariadb_bin`),
    totalmente à parte do venv principal, e invoca `dbt compile` via
    `subprocess`. Postgres usa `dbtRunner` em processo, no venv normal.
- [x] `mypy --strict`/`ruff` limpos.

## Testes

- [x] `dbt parse`/`dbt compile` sobre o projeto gerado, em teste de
      integração (`tests/integration/generators/dbt/`), contra Postgres
      **e** MariaDB reais (testcontainers) — pipeline completo (`Extrator`
      real → `SobrescritaDeTabela` → `iniciar_contexto` → `GeradorDbt`),
      cobrindo os tipos do achado 1 (BIGINT/TEXT/DECIMAL/BOOLEAN/JSON/
      DOUBLE/TIMESTAMP-DATETIME com precisão fracionária real) e os
      identificadores do achado 2 (`order`, `left`).
  - Confirmou a tabela de dispatch inteira sem nenhuma correção
    necessária, incluindo o único item que tinha ficado como hipótese
    não testada (`TIME WITH TIME ZONE`/precisão fracionária real).
  - **Achado real do próprio teste, não relacionado a CAST/quoting:**
    `dbt_project.yml` com `meta` na raiz (existente desde antes desta
    issue) não é aceito pelo parsing estrito do dbt-core moderno
    (`meta` de projeto na raiz nunca foi uma chave suportada do schema).
    Corrigido movendo pra `models.ddf_staging.+meta.generated_at`, local
    válido que ainda propaga pra todos os models do projeto.
  - Teste dedicado de `TestErro`: `NUMERIC` sem precisão/escala falha
    explícito no `dbt compile` do MariaDB (`raise_compiler_error`),
    compila normal no Postgres — confirma o mecanismo do achado 1.
- [x] Unit: teste novo reproduzindo o cenário numérico de falso-positivo de
      `unique`/`not_null` amostral (piso exato, abaixo do piso, fato
      estrutural prevalecendo), confirmando piso+`warn` aplicados
- [x] Unit: coluna com FK composta + FK single-column própria válida —
      `relationships` da FK simples presente, sem supressão indevida
- [x] Unit: coluna só em FK composta (sem FK própria) — `relationships`
      suprimido, sem `Aviso` (nada de fato suprimido)
- [x] Regressão: suíte completa de `test_gerador_dbt.py` segue verde após as
      mudanças de CAST/quoting (ajustar asserções de string existentes que
      hoje esperam o CAST antigo sem macro/quoting)

## Verificação final

- [x] `mypy --strict src` (97 arquivos) + `ruff check .` limpos
- [x] `pytest tests/unit` (650 testes) + `pytest tests/integration` (71
      testes, Postgres+MariaDB reais) verdes
- [x] `dbt compile` real contra projeto gerado (Postgres via `dbtRunner`,
      MariaDB via subprocess no venv isolado) — coberto pelo teste de
      integração automatizado do achado 5, substitui a verificação manual
      original

## Follow-ups fora do escopo desta issue (registrados, não implementados)

- Captura de tipos `YEAR`/`BINARY`/`VARBINARY`/`BLOB`/`BIT` no MariaDB
  (hoje `UNKNOWN`) — achado da auditoria pontual sobre
  `mariadb/mapeamento_de_tipos.py` durante esta sessão, sem relação direta
  com o CAST corrigido aqui. Reconfirmado como fora de escopo na segunda
  rodada de banca (ver abaixo) — permanece só como limitação documentada,
  sem issue nova.
- Modelar signedness (`BIGINT UNSIGNED`) em `TipoDeDado` — `BIGINT
  UNSIGNED` > 2^63-1 vira negativo em silêncio no `CAST(x AS SIGNED)` do
  MariaDB; fica como limitação documentada, não mudança de domínio.
  Reconfirmado como fora de escopo na segunda rodada de banca — exigiria
  campo novo (`sem_sinal: bool`, mesmo padrão de `precisao_fracionaria`) +
  captura no extrator MariaDB + lógica nova no macro `cast_type`, mudança
  de domínio real, não um fix pontual.

## Segunda rodada de banca — revisão do diff final, antes do PR

Com os 5 achados implementados e commitados (13 commits,
`development..HEAD`), o usuário convocou a banca completa (arquiteto-de-
software + engenheiro-de-dados + po-revisor) em modo automático, só
leitura, pra revisar o diff final antes de abrir o PR. Veredito dos três:
**aprovado** (arquiteto com ressalvas menores, não bloqueantes). Três
achados acionáveis, todos implementados nesta mesma sessão:

- [x] **Bug de classificação de teste** (arquiteto) —
      `test_numeric_sem_precisao_compila_normalmente_no_postgres` estava
      dentro de `TestErro`, mas afirma sucesso de compilação (contraste
      positivo do caso de erro, não um erro). Movido para `TestFeliz`;
      helper `_tabela_numeric_sem_precisao` virou função de módulo
      (consumida pelas duas classes).
- [x] **Lacunas no teste de integração real** (engenheiro de dados) —
      `REAL`/`FLOAT`, `TIME`/`TIME WITH TIME ZONE` e FK composta
      (`composite_relationships`) nunca tinham passado por `dbt compile`
      real, só por asserção de string em teste unitário.
  - `tests/integration/generators/dbt/conftest.py`: tabela `diversos`
    (Postgres e MariaDB) ganhou colunas `nota REAL`/`FLOAT` e `hora TIME`;
    Postgres ganhou também `hora_tz TIME WITH TIME ZONE` (MariaDB não tem
    esse tipo). Nova tabela `pai`/`filho_fk_composta` com FK composta real
    nos dois motores.
  - `test_gerador_dbt_compile_integration.py`: 3 testes novos em
    `TestFeliz` — `TIME WITH TIME ZONE` no MariaDB via tabela **sintética**
    (o motor não produz esse tipo por extração real, já que não tem
    `timetz`; é o único jeito de exercitar essa entrada do dispatch contra
    `dbt compile` de verdade) e FK composta real (Postgres via `dbtRunner`,
    MariaDB via subprocess), extraindo as duas tabelas e gerando o projeto
    junto — `composite_relationships` só é gerado com a tabela referenciada
    presente no lote (achado 4 da primeira rodada). Todos os 7 testes do
    arquivo passaram contra containers reais (não só coletados).
- [x] **Limitação de BIGINT UNSIGNED não chega ao usuário final**
      (engenheiro de dados, endossado pelo PO) — só documentada no
      registry-plan interno; quem lê é o time ddf, não quem consome o
      projeto dbt gerado.
  - `_sql.py`: `_tem_coluna_bigint` novo (mesmo padrão de
    `_precisa_cast_type`).
  - `gerador_dbt.py`/`_yaml.py`: `usa_bigint` calculado e repassado a
    `_renderizar_readme`.
  - `readme.md.jinja2`: nota condicional explicando a limitação, sempre
    que há BIGINT no lote (ddf não sabe em tempo de geração se o destino
    será MariaDB — única engine onde o problema existe, Postgres não tem
    inteiro sem sinal).
  - Testes unit novos: com BIGINT no lote (nota aparece) / sem BIGINT
    (nota ausente).
- Descartado pelo usuário: abrir issue no GitHub para os follow-ups
  (YEAR/BINARY/VARBINARY/BLOB/BIT, signedness de BIGINT UNSIGNED) — ambos
  permanecem só como limitação documentada nesta issue.
- Reorganização de `plan/registry-plan/` em pastas por fase (commit
  `76f3c80`, já commitado antes desta rodada) e demais itens "nice-to-have"
  sem ação concreta pedida (indireção não-decorativa em `_expressao_quote`/
  `_nome_quotado`, helpers com único call site mas mesmo padrão do módulo)
  — sem ação, confirmados como não-problema pela própria banca.

Verificação final desta rodada: `mypy --strict src` (97 arquivos) +
`ruff check .` limpos; `pytest tests/unit` (652 testes) verde;
`pytest tests/integration/generators/dbt/` (7 testes, Postgres+MariaDB
reais) verde.

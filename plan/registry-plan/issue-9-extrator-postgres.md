# Issue #9 — feat: ExtratorPostgres

## Decisões tomadas na discussão prévia (antes de implementar)

> **`information_schema.tables` não tem contagem de linhas no Postgres.** O
> `low_level_design.md` original dizia "lê `total_linhas` via
> `information_schema.tables`" — isso é comportamento do MySQL, não existe no
> Postgres. Decisão: usar `pg_catalog.pg_class.reltuples` (estimativa, O(1),
> atualizada por `ANALYZE`/autovacuum) em vez de `SELECT COUNT(*)` (exato,
> porém caro em tabelas grandes). `docs/low_level_design.md` atualizado com a
> ressalva de que é estimativa — enfraquece um pouco a garantia que
> `MetadadosDeAmostra.total_linhas` documentava desde a #6 ("universo
> considerado pela `EstrategiaDeAmostragem`"), mas evita `COUNT(*)` competindo
> com a própria amostragem por I/O.

> **Validação redundante removida.** O texto original do
> `low_level_design.md` pedia que `ExtratorPostgres.__init__` validasse
> `max_conexoes >= max_trabalhadores` — mas isso já é garantido por
> `ConfiguracaoDeExtracao._valida_max_conexoes` (Pydantic, não dá pra
> construir uma instância inválida). Uma segunda checagem no `__init__` nunca
> dispararia. Removida do doc e não implementada.

> **Reabertura de escopo da #5 — `domain/model/common/tipo_de_dado.py`.**
> Durante o mapeamento de tipos Postgres → `TipoDeDado`, identificamos que a
> tabela original do `low_level_design.md` não cobria `smallint`, `real`,
> `double precision`, `character(n)`, `uuid`, `time` — e que forçar esses
> tipos em categorias existentes (`NUMERIC`, `VARCHAR`) produziria casts SQL
> incorretos no `GeradorDbt` (issue futura). `CategoriaDeDado` ganha 4 valores
> novos:
> - **`FLOAT`** (`real`, `double precision`) — separada de `NUMERIC` porque
>   float binário tem largura fixa pelo nome do tipo, sem `precisao`/`escala`
>   escolhidos pelo usuário como em `numeric(p,s)`. Sem atributos extras.
> - **`CHAR`** (`character(n)`) — separada de `VARCHAR` porque comprimento
>   fixo (com padding) é um conceito diferente de comprimento máximo. Ganha
>   atributo próprio `tamanho_fixo` (não reaproveita `tamanho_maximo`).
> - **`UUID`** — sem atributos extras.
> - **`TIME`** — sem atributos extras próprios, mas compartilha o atributo
>   novo `com_timezone` com `TIMESTAMP` (ver abaixo).
>
> `smallint` mapeia para `INTEGER` existente (mesma categoria de `integer`).
>
> **`TipoDeDado` ganha 2 campos:** `tamanho_fixo: int | None` (exclusivo de
> `CHAR`) e `com_timezone: bool | None` (compartilhado entre `TIMESTAMP` e
> `TIME`, capturando a distinção `with/without time zone` do Postgres que a
> v1 original não previa). `_ATRIBUTOS_PERMITIDOS` atualizado com as novas
> entradas. Testes novos em `tests/unit/domain/model/common/test_tipo_de_dado.py`
> (feliz por categoria nova, erro esperado por combinação inválida, ex.:
> `CHAR` com `tamanho_maximo` em vez de `tamanho_fixo`).

> **Mecanismo do teste de integração: `testcontainers-python`.** Nova
> dependência de dev (extra `postgres`) — sobe um container Postgres
> descartável por execução de teste, reprodutível em CI sem depender de infra
> externa já no ar. Alternativa descartada: `docker-compose` + fixture manual
> (exigiria orquestração externa ao `pytest`).

> **`LimiteAleatorio` extinta, substituída por `PercentualDeLinhas` — reabre
> escopo da #8.** Ao revisar como a CLI vai coletar `--sample-size` de um
> usuário com dezenas de tabelas de tamanhos muito diferentes, ficou claro que
> um LIMIT absoluto fixo por execução não escala: 500 linhas é quase a tabela
> inteira numa tabela de 600 linhas e insignificante numa de 50 milhões, e não
> há como o usuário calibrar isso por tabela numa CLI.
>
> Essa discussão passou por duas rodadas:
>
> 1. Primeira tentativa: `PercentualDeLinhas` calculando `LIMIT` em **Python**
>    (`round(total_linhas * percentual / 100)`), mantendo `consulta()` no
>    Port — decisão tomada para evitar `TABLESAMPLE` (sintaxe do Postgres) e
>    preservar `EstrategiaDeAmostragem` agnóstica de banco.
> 2. Ao revisar essa primeira versão, identificamos um problema mais sério:
>    `LIMIT` sem `ORDER BY` retorna as linhas na ordem física/de inserção da
>    tabela — **enviesado**, não uma amostra estatística de verdade (as
>    "primeiras N linhas" tendem a ser as mais antigas, ou seguir qualquer
>    padrão de clustering físico). Isso importa muito: a amostra alimenta
>    diretamente os Analisadores (`percentual_nulo`, `percentual_unico`), e um
>    viés sistemático na amostra vira um viés sistemático nas métricas
>    reportadas ao usuário.
>
> As alternativas sem viés (`TABLESAMPLE BERNOULLI`, sorteio linha a linha; ou
> `ORDER BY random() LIMIT N`, mais caro por exigir sort completo) exigem SQL
> específico de qualquer forma — não tem como fugir disso, amostragem sem
> viés sempre depende do dialeto da fonte. Isso expôs que a divisão de
> responsabilidade estava errada desde o início: `EstrategiaDeAmostragem` não
> devia gerar SQL nenhum. **Decisão final:** `EstrategiaDeAmostragem` vira uma
> política pura (`nome`, `percentual`), sem método `consulta()` — quem traduz
> a política numa query concreta é o `Extrator` (que já é, por definição,
> acoplado ao dialeto da própria fonte; `ExtratorPostgres` já lê
> `information_schema`, já é 100% Postgres). Isso resolve o receio de
> acoplamento sem custo real: nenhum `Extrator` futuro precisa de uma classe
> de `EstrategiaDeAmostragem` própria, cada um só interpreta o mesmo
> `percentual` do jeito que fizer sentido no próprio banco (`ExtratorPostgres`
> usa `TABLESAMPLE BERNOULLI`). `total_linhas` sai do Port inteiramente —
> `BERNOULLI(p)` usa percentual diretamente, não precisa saber a contagem de
> linhas antecipadamente. `MetadadosDeAmostra.tamanho_amostra` deixa de ser
> calculado e passa a ser observado (`len(dataframe)` após carregar a
> amostra), já que `TABLESAMPLE` decide dinamicamente quantas linhas sorteia.
> `tamanho_amostra=0` (percentual baixo numa tabela pequena) continua aceito
> como estado real, mesmo critério já usado em `MetadadosDeAmostra` desde a
> #6.

> **Subpasta `extractors/postgres/` — reabre convenção de `engineer_guidelines.md`.**
> `mapeamento_de_tipos.py` (vocabulário de `information_schema.columns.data_type`)
> é 100% específico do Postgres — um `ExtratorMariaDB` futuro precisaria de um
> mapeamento totalmente diferente. Deixá-lo lado a lado com
> `percentual_de_linhas.py` (que é agnóstico de fonte, reutilizável por
> qualquer `Extrator`) na mesma pasta `extractors/` confundia o que é
> compartilhado com o que é específico de uma fonte. Decisão: subpasta por
> fonte (`extractors/postgres/` com `extrator_postgres.py` e
> `mapeamento_de_tipos.py`), espelhada em `tests/unit/.../extractors/postgres/`
> e `tests/integration/extractors/postgres/`. `percentual_de_linhas.py`
> permanece no nível de `extractors/`. `docs/engineer_guidelines.md` atualizado.

> **`types-psycopg2` adicionada ao grupo dev.** `psycopg2-binary` não embute
> `py.typed`/stubs — sem `types-psycopg2`, qualquer `import psycopg2` quebra
> `mypy --strict` com `Library stubs not installed`. Necessária pra tipar
> `ThreadedConnectionPool`, `cursor.description`, `psycopg2.sql.Identifier`/
> `Literal` etc.

> **`conexao.autocommit = True` em toda extração.** `ExtratorPostgres` só lê
> dados — nunca escreve — então não há razão pra manter uma transação aberta
> quando a conexão volta pro pool sem `commit()`/`rollback()` explícito.

> **`MetadadosDeAmostra.total_linhas` removido — reabre escopo da #6.** Ao
> implementar `extrair_tabela`, o mesmo valor de `total_linhas` (via
> `reltuples`) acabava preenchendo tanto `TabelaExtraida.total_linhas` quanto
> `MetadadosDeAmostra.total_linhas` — o que gerou dúvida sobre se isso era
> intencional. Investigando, confirmamos que a distinção documentada na #6
> ("universo considerado pela `EstrategiaDeAmostragem`", conceitualmente
> diferente do total real) nunca teve consumidor real: nenhum
> `model_validator` chegou a impor `tamanho_amostra <= total_linhas` (só
> existia na documentação, nunca no código), e nem o Analisador nem os
> Geradores liam esse campo — os Geradores exibem `TabelaExtraida.total_linhas`
> (`low_level_design.md:111`, `:804`). Era complexidade especulativa para uma
> estratégia futura filtrada (`WHERE`) que não existe. Decisão: campo
> removido de `MetadadosDeAmostra`. `TabelaExtraida.total_linhas` é a única
> fonte de verdade pro total de linhas da tabela.

> **Bug real encontrado ao preparar o teste de integração: pool preguiçoso.**
> `ThreadedConnectionPool` conecta `minconn` conexões já no `__init__` —
> confirmado empiricamente com um DSN inválido, que levanta `OperationalError`
> na construção do pool, não em `getconn()`. Isso contradizia o contrato
> documentado (`Falha("Não foi possível conectar: <detalhe>")` é comportamento
> de `extrair_tabela`, não da construção do `Extrator`) e nenhum teste unitário
> pegou isso, porque todos mockavam `ThreadedConnectionPool` inteiro — testavam
> que o código trata `OperationalError`, não que o psycopg2 a levanta nesse
> ponto exato do fluxo. Corrigido: `ExtratorPostgres.__init__` só guarda `dsn`/
> `configuracao`; o pool é criado sob demanda em `_obter_pool()`, chamado no
> início de `listar_tabelas`/`extrair_tabela`, com o mesmo `try/except
> OperationalError` que já existia — agora cobrindo o caso real. Teste novo
> (`test_listar_tabelas_com_dsn_invalido_retorna_falha_sem_lancar_excecao`)
> força esse cenário via `pool_classe_fake.side_effect`, não só `getconn.side_effect`.
> Lição: mockar a interface externa inteira (a classe do driver) esconde bugs
> de *quando* uma operação de I/O realmente acontece — só o teste de
> integração contra Postgres real (ainda pendente) prova isso de verdade.

> **`FLOAT` ganha `com_precisao_dupla` — correção de inconsistência dentro da
> própria #9.** Na primeira versão, `real` e `double precision` colapsavam em
> `FLOAT` sem nenhum atributo — mas eles têm larguras diferentes (4 bytes/~6
> dígitos vs. 8 bytes/~15 dígitos), e o próprio motivo de existir de `FLOAT`
> era não perder informação relevante pro cast do `GeradorDbt`. Revisando o
> mesmo padrão já aplicado em `TIME`/`TIMESTAMP` (`com_timezone`, categoria
> única + atributo booleano em vez de categorias separadas), aplicamos a
> mesma solução aqui: `TipoDeDado.com_precisao_dupla: bool | None`,
> `_ATRIBUTOS_PERMITIDOS[FLOAT] = {"com_precisao_dupla"}`, `real` mapeia com
> `com_precisao_dupla=False`, `double precision` com `True`. Testes
> atualizados em `test_tipo_de_dado.py` e `test_mapeamento_de_tipos.py`.

## Escopo desta issue

- [x] `domain/model/common/tipo_de_dado.py` — `CategoriaDeDado.FLOAT/CHAR/UUID/TIME`,
      `TipoDeDado.tamanho_fixo`/`com_timezone`, `_ATRIBUTOS_PERMITIDOS` atualizado
- [x] `domain/ports/estrategia_de_amostragem.py` — `consulta()` removido;
      Port vira `nome` + `percentual`, sem gerar SQL
- [x] `infrastructure/adapters/extractors/percentual_de_linhas.py` —
      `PercentualDeLinhas(EstrategiaDeAmostragem)`, só guarda `percentual`
- [x] `infrastructure/adapters/extractors/postgres/mapeamento_de_tipos.py` —
      `mapear_tipo_postgres()`, função pura, testada isoladamente
- [x] `infrastructure/adapters/extractors/postgres/extrator_postgres.py` — `ExtratorPostgres(Extrator)`:
  - Pool preguiçoso: `__init__` só guarda `dsn`/`configuracao`; `ThreadedConnectionPool`
    criado sob demanda em `_obter_pool()`, no primeiro `listar_tabelas`/`extrair_tabela`
  - `listar_tabelas` via `information_schema.tables` (`table_type = 'BASE TABLE'`)
  - `extrair_tabela`:
    - Colunas via `information_schema.columns`
    - PK via `table_constraints` + `key_column_usage`
    - FK via `table_constraints` + `key_column_usage` + `constraint_column_usage`
    - `total_linhas` via `pg_catalog.pg_class.reltuples` (independente da amostragem)
    - Amostra via `TABLESAMPLE BERNOULLI(configuracao.estrategia.percentual)` → `pl.DataFrame`
    - `tamanho_amostra = len(dataframe)` (observado, não calculado)
  - Mapeamento de tipos completo (tabela em `docs/low_level_design.md`)
  - `Falha("Schema 'x' ou tabela 'y' não encontrada.")` / `Falha("Não foi possível conectar: <detalhe>")`
- [x] `pyproject.toml` — `testcontainers[postgres]` no grupo dev

## Testes

### `tests/unit/infrastructure/adapters/extractors/` (com `conftest.py`)

- [x] `PercentualDeLinhas`: caminho feliz (conformidade ao Port, `percentual`
      retorna o valor configurado, `nome`), erro esperado (`percentual` fora
      de `(0, 100]`), borda (`percentual=100`)

### `tests/unit/infrastructure/adapters/extractors/postgres/`

- [x] `mapear_tipo_postgres`: caminho feliz por categoria (varchar, char,
      text, numeric, integer incl. smallint, bigint, float incl.
      real/double precision, boolean, timestamp com/sem tz, time com/sem tz,
      date, json/jsonb, uuid), borda (tipo desconhecido → `UNKNOWN`)
- [x] `ExtratorPostgres`: conformidade ao Port `Extrator`, construção (pool
      criado com os parâmetros corretos no 1º uso, pool reaproveitado entre
      chamadas), `listar_tabelas` (feliz/borda lista vazia), `extrair_tabela`
      (feliz completo — colunas/PK/FK/total_linhas/amostra —, erro schema/
      tabela inexistente, erro DSN inválido na criação do pool, erro conexão
      recusada em `getconn`, borda `reltuples` negativo)

### `tests/unit/domain/model/common/test_tipo_de_dado.py` (extensão da #5)

- [x] Caminho feliz: `FLOAT`, `CHAR` com `tamanho_fixo`, `UUID`, `TIME`/`TIMESTAMP`
      com `com_timezone`
- [x] Erro esperado: `CHAR` com `tamanho_maximo` (em vez de `tamanho_fixo`),
      `FLOAT`/`UUID` com qualquer atributo extra

### `tests/integration/extractors/postgres/` (via `testcontainers`, Postgres 16 real)

- [x] `listar_tabelas`: caminho feliz (lista ordenada por nome), borda (schema
      sem tabelas → lista vazia)
- [x] `extrair_tabela`: caminho feliz (estrutura completa: colunas, PK, FK,
      `total_linhas`, amostra, metadados; mapeamento `TIMESTAMP com_timezone`),
      erro esperado (schema/tabela inexistente → `Falha`), erro esperado (DSN
      inválido/conexão recusada → `Falha`)
- [x] Schema semeado por sessão (`clientes`/`pedidos`/schema `vazio`) em
      `conftest.py`; `PercentualDeLinhas(percentual=100)` garante amostra
      determinística nos testes (sem depender de aleatoriedade do `BERNOULLI`)

## Pendências para próximas issues (não resolvidas aqui)

- `SobrescritaDeTabela` e `OrquestradorParalelo` (issue #7/#10) consomem
  `TabelaExtraida` produzida por `ExtratorPostgres`, mas não são implementados
  aqui.
- `GeradorDbt` (issue futura) é o consumidor real da distinção
  `FLOAT`/`NUMERIC`/`CHAR`/`VARCHAR`/`com_timezone` no cast SQL — não
  implementado nesta issue, só o modelo que a suporta.

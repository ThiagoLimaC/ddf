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

## Escopo desta issue

- [ ] `domain/model/common/tipo_de_dado.py` — `CategoriaDeDado.FLOAT/CHAR/UUID/TIME`,
      `TipoDeDado.tamanho_fixo`/`com_timezone`, `_ATRIBUTOS_PERMITIDOS` atualizado
- [ ] `infrastructure/adapters/extractors/limite_aleatorio.py` — `LimiteAleatorio(EstrategiaDeAmostragem)`
- [ ] `infrastructure/adapters/extractors/extrator_postgres.py` — `ExtratorPostgres(Extrator)`:
  - Construção com `ThreadedConnectionPool(minconn=1, maxconn=configuracao.max_conexoes, dsn=dsn)`
  - `listar_tabelas` via `information_schema.tables` (`table_type = 'BASE TABLE'`)
  - `extrair_tabela`:
    - Colunas via `information_schema.columns`
    - PK via `table_constraints` + `key_column_usage`
    - FK via `table_constraints` + `key_column_usage` + `constraint_column_usage`
    - `total_linhas` via `pg_catalog.pg_class.reltuples`
    - Amostra via `configuracao.estrategia.consulta(schema, tabela)` → `pl.DataFrame`
  - Mapeamento de tipos completo (tabela em `docs/low_level_design.md`)
  - `Falha("Schema 'x' ou tabela 'y' não encontrada.")` / `Falha("Não foi possível conectar: <detalhe>")`
- [ ] `pyproject.toml` — `testcontainers[postgres]` no grupo dev

## Testes

### `tests/unit/infrastructure/adapters/extractors/` (com `conftest.py`)

- [ ] `LimiteAleatorio`: caminho feliz (SQL formatada corretamente com schema/tabela/tamanho),
      borda (`tamanho=1`)
- [ ] Função de mapeamento de tipo Postgres → `TipoDeDado`: caminho feliz por
      categoria (varchar, char, text, numeric, integer incl. smallint, bigint,
      float incl. real/double precision, boolean, timestamp com/sem tz, time
      com/sem tz, date, json/jsonb, uuid), borda (tipo desconhecido → `UNKNOWN`)
- [ ] Construção de `ExtratorPostgres`: caminho feliz (pool criado com os
      parâmetros corretos, `ThreadedConnectionPool` mockado)

### `tests/unit/domain/model/common/test_tipo_de_dado.py` (extensão da #5)

- [ ] Caminho feliz: `FLOAT`, `CHAR` com `tamanho_fixo`, `UUID`, `TIME`/`TIMESTAMP`
      com `com_timezone`
- [ ] Erro esperado: `CHAR` com `tamanho_maximo` (em vez de `tamanho_fixo`),
      `FLOAT`/`UUID` com qualquer atributo extra

### `tests/integration/extractors/` (via `testcontainers`)

- [ ] `listar_tabelas`: caminho feliz (lista ordenada por nome), borda (schema
      sem tabelas → lista vazia)
- [ ] `extrair_tabela`: caminho feliz (estrutura completa: colunas, PK, FK,
      `total_linhas`, amostra, metadados), erro esperado (schema/tabela
      inexistente → `Falha`), erro esperado (DSN inválido/conexão recusada →
      `Falha`)

## Pendências para próximas issues (não resolvidas aqui)

- `SobrescritaDeTabela` e `OrquestradorParalelo` (issue #7/#10) consomem
  `TabelaExtraida` produzida por `ExtratorPostgres`, mas não são implementados
  aqui.
- `GeradorDbt` (issue futura) é o consumidor real da distinção
  `FLOAT`/`NUMERIC`/`CHAR`/`VARCHAR`/`com_timezone` no cast SQL — não
  implementado nesta issue, só o modelo que a suporta.

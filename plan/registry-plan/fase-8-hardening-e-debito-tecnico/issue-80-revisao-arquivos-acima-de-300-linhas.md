# Issue #80 — revisão de arquivos com mais de 300 linhas para responsabilidade única

## Contexto

Levantamento de tamanho de arquivo mostrou 5 arquivos de produção acima de
300 linhas:

- `extractors/mariadb/extrator_mariadb.py` — 504 linhas
- `extractors/postgres/extrator_postgres.py` — 489 linhas
- `generators/gerador_dbt.py` — 440 linhas
- `generators/gerador_markdown.py` — 340 linhas
- `generators/gerador_contexto_de_ia.py` — 335 linhas

A hipótese da issue era que algum desses arquivos misturasse responsabilidades
(ex.: parsing de schema + geração de query + formatação de saída) e valesse
quebrar em componentes menores.

## Decisão tomada na discussão prévia

> **Nenhum dos 5 arquivos tem responsabilidade misturada (avaliação do
> arquiteto-de-software, 2026-07-26).** Para cada um, o arquiteto tentou
> nomear 2+ razões de mudança distintas — todas colapsaram numa só ("como
> este dialeto/formato de saída se comporta"). São Adapters extensos porém
> coesos: SRP já respeitado. `gerador_markdown.py` em particular fica sem
> nenhum achado — é só formatação Jinja, sem heurística de negócio
> comparável aos outros dois Geradores.
>
> Em vez de split por arquivo, o achado real é duplicação pontual que já
> segue o precedente de extração agnóstica de fonte do projeto
> (`seed_efetivo`, `construir_colunas_fk`, `construir_metadados_de_amostra`,
> `_metricas.py`):
>
> 1. Bloco `match requisicao_efetiva` para `total_linhas_final` duplicado
>    verbatim entre `extrator_postgres.py:459-465` e
>    `extrator_mariadb.py:475-481` (confirmado via `grep`, 2 ocorrências).
> 2. Boilerplate de aquisição/liberação de conexão (pool → `OperationalError`
>    → `Falha` → `finally` release, mais semáforo no Postgres) repetido 3-4x
>    dentro de cada classe — não compartilhado *entre* os dois Extratores
>    (APIs de driver divergem), mas dentro de cada um.
> 3. Predicado estatístico "coluna é categórica confiável"
>    (`percentual_unico < 10.0` + cobertura via
>    `_cobertura_dos_valores_frequentes`) duplicado entre
>    `gerador_dbt.py:283-298` e `gerador_contexto_de_ia.py:152-190`, com o
>    literal `10.0` hardcoded nos dois lugares.
>
> **Threshold de 10% fica hardcoded no predicado fundido, sem parâmetro**
> (decisão do usuário, 2026-07-26) — os dois Geradores devem sempre
> concordar nesse critério; se um dia precisar divergir, é mudança
> deliberada no predicado compartilhado, não parametrização preventiva. Já
> `tamanho_amostra_minimo` continua parâmetro (0 no dbt, 100 no contexto de
> IA — divergência real e já existente hoje, não hipotética).
>
> Reabrir com o engenheiro-de-dados antes de implementar o item 2: extrair o
> context manager de conexão pode mudar sutilmente a ordem de
> acquire/release do semáforo do `ExtratorPostgres` sob concorrência —
> avaliar se o teste de concorrência existente cobre isso ou se precisa de
> um novo.
>
> **Módulo de queries SQL por Extrator incluído no escopo, por decisão do
> usuário (2026-07-26), revertendo a recomendação inicial do arquiteto.**
> O arquiteto havia descartado isso por não ser reuso real (cada query tem 1
> call site) — mas o usuário apontou que mover constante + comentário juntos
> para um módulo próprio não é o alvo do critério anti-indireção-decorativa
> (que é sobre extração de função, não reorganização de arquivo), e não há
> risco de segurança ou de violar o system design nisso. Vira reorganização
> pura (`_queries.py` por Extrator), sem mudança de comportamento.
>
> **Item 1 (`total_linhas_final`) removido do escopo (decisão do usuário,
> 2026-07-26), depois de implementado e testado (mypy/ruff/pytest limpos).**
> Usuário avaliou que a extração era redução desnecessária e pediu para
> manter o bloco `match`/`case` como está, duplicado nos dois Extratores.
> Revertido via `git checkout` (os dois Extratores não tinham nenhuma outra
> mudança commitada) e `total_linhas_final.py` removido.
>
> **Item 3 (`_coluna_e_categorica_confiavel`) removido do escopo (decisão
> do usuário, 2026-07-26), depois de implementado e testado (mypy/ruff/
> pytest limpos).** Mesmo motivo do item 1 — redução desnecessária.
> `gerador_dbt.py`, `gerador_contexto_de_ia.py` e `_metricas.py`
> revertidos via `git checkout`. O predicado `percentual_unico < 10.0` +
> cobertura continua duplicado entre os dois Geradores, como estava antes
> da issue.

## Escopo desta issue

- [x] Context manager privado de conexão em `ExtratorPostgres`
      (`self._conexao()`, cobrindo pool + semáforo + `Falha` em
      `OperationalError` + release garantido) — substitui a repetição em
      `listar_escopos`/`listar_tabelas`/`_obter_metadados_schema`/`extrair_tabela`.
      Teste de concorrência equivalente já existia
      (`test_max_conexoes_um_faz_segunda_chamada_concorrente_esperar`) e
      passou sem alteração contra o código novo — nenhum teste novo
      necessário.
- [x] Context manager privado equivalente em `ExtratorMariaDB` (sem
      semáforo — só pool, `PooledDB(blocking=True)` já bloqueia
      internamente) — substitui a repetição em
      `listar_escopos`/`listar_tabelas`/`extrair_tabela`
- [x] `extractors/postgres/_queries.py` recebe as 7 constantes SQL de
      `extrator_postgres.py` (com os comentários-justificativa movidos
      junto); `extrator_postgres.py` importa do módulo irmão
- [x] `extractors/mariadb/_queries.py` recebe as 8 constantes SQL de
      `extrator_mariadb.py` (idem); `extrator_mariadb.py` importa do
      módulo irmão
- [x] Re-medir `wc -l` dos 5 arquivos após as extrações — resultado final:

  | Arquivo | Antes | Depois |
  |---|---|---|
  | `extrator_postgres.py` | 489 | 375 |
  | `extrator_mariadb.py` | 504 | 451 |
  | `gerador_dbt.py` | 440 | 440 (revertido) |
  | `gerador_markdown.py` | 340 | 340 (sem achado) |
  | `gerador_contexto_de_ia.py` | 335 | 335 (revertido) |
  | `postgres/_queries.py` (novo) | — | 113 |
  | `mariadb/_queries.py` (novo) | — | 76 |

  A redução veio inteiramente do `_queries.py` — os itens 1 e 3
  (`total_linhas_final`, `_coluna_e_categorica_confiavel`) foram removidos
  do escopo (ver decisões acima), então os Geradores voltaram ao tamanho
  original e os Extratores só refletem a extração de queries + context
  manager (que reduz pouca linha por eliminar duplicação, não por mover
  código pra outro lugar).
- [x] `mypy --strict src` + `ruff check .` + `pytest tests/unit` (379
      testes) limpos após cada etapa

## Fora de escopo (avaliado e descartado)

- Split de `gerador_markdown.py` — sem achado, arquivo coeso.
- Abstração de pooling compartilhada entre Postgres e MariaDB — APIs de
  driver divergem o bastante (semáforo só existe no Postgres) para custar
  mais do que economiza.
- Módulo próprio para as heurísticas de sugestão (`_sugestoes_de_teste`,
  `_sugestao_de_filtro`) — cada uma tem 1 call site dentro do próprio
  Gerador; o output que produzem é específico do formato de saída, não
  reuso genuíno além do predicado já extraído no item acima.

# Issue #57 — fix: corrige crash de ARRAY no Postgres e classificação incorreta de JSON no MariaDB

## Contexto

Achados bloqueantes da auditoria de engenharia de dados pré-CLI (issue #56,
Fase 1), validados empiricamente contra Postgres 15 e MariaDB 11 reais —
extraído de #56 para permitir merge independente.

- Coluna `ARRAY` do Postgres derruba `AnalisadorDeMetricasDeColuna` —
  `.min()`/`.max()` levantam `polars.exceptions.InvalidOperationError` para
  dtype `pl.List`, não capturado por nenhuma camada.
- `JSON` do MariaDB é sempre classificado como `TEXT` —
  `information_schema.columns.DATA_TYPE` nunca reporta `"json"` contra o
  motor real (sempre `"longtext"`); a classificação correta depende do
  `CHECK(json_valid(...))` implícito.

## Decisão revisitada durante a implementação

> **`ARRAY` do Postgres — categoria própria, não `UNKNOWN`.** A decisão
> original da issue #56 era só falha graciosa (categoria `UNKNOWN`), com
> suporte semântico pleno fora de escopo da v1. Revisitada durante a
> implementação: `CategoriaDeDado.ARRAY` ganhou categoria própria + atributo
> `elemento: CategoriaDeDado | None` (sem precisão do elemento — opção
> "leve", não um tipo recursivo), resolvido a partir de `udt_name` do
> Postgres (não lido antes). Confirmado com o usuário (PO).
> **Unificação de `mapear_tipo_postgres` via `udt_name`** — decisão tomada
> já durante a implementação (não fazia parte do plano original): a tabela
> `_CATEGORIAS_SIMPLES`, que resolveria só o elemento do `ARRAY`, cobria a
> maioria dos mesmos mapeamentos já feitos por `data_type` — unificado num
> único dispatch por `udt_name` (nome canônico interno do Postgres, uma
> palavra), eliminando a duplicação em vez de manter as duas tabelas lado a
> lado.

Plano completo de implementação: `/home/dev/.claude/plans/cosmic-exploring-matsumoto.md`
(sessão de planejamento com Claude, 2026-07-21).

## Escopo desta issue

- [x] `AnalisadorDeMetricasDeColuna`: normalização de série (antes só
      `pl.Object`) cobre `pl.List` também — corrige `InvalidOperationError`
      de `.min()`/`.max()` em coluna `ARRAY`; funções renomeadas para
      `_normalizar_serie_nao_nativa`/`_representar_valor_nao_nativo`
- [x] `TipoDeDado`: `CategoriaDeDado.ARRAY` + atributo `elemento:
      CategoriaDeDado | None`
- [x] `mapear_tipo_postgres`: refatorado pra despachar por `udt_name` (nome
      canônico de uma palavra por tipo), não mais por `data_type`
      (multi-word) — elimina tabela duplicada, `_CATEGORIAS_SIMPLES` serve
      tanto de fallback do tipo externo quanto de resolução do `elemento`
      do `ARRAY`; detecção de array via prefixo `"_"` do `udt_name`
- [x] `ExtratorPostgres`: `udt_name` na query de colunas (substitui
      `data_type`, agora sem uso), repassado até o mapeamento
- [x] `GeradorMarkdown`/`GeradorDbt`: renderizam `ARRAY` (`"<ELEMENTO>[]"`
      no Markdown, `CAST(col AS <ELEMENTO>[])` no dbt quando elemento
      conhecido; passthrough sem `CAST` quando não — `_tem_cast_seguro`
      substitui a checagem que antes só olhava `UNKNOWN`)
- [x] `ExtratorMariaDB`: nova query em `information_schema.CHECK_CONSTRAINTS`
      + `_extrair_coluna_json_valid` (função pura, regex, validada contra
      MariaDB 11 real) — corrige `JSON` classificado como `TEXT`;
      `CHECK_CONSTRAINTS` não tem `TABLE_NAME`, defesa via cruzamento com
      colunas reais da tabela (`_colunas_json_de_check_clauses`); entrada
      morta `"json"` removida de `_CATEGORIAS_SIMPLES` do MariaDB
- [x] `mypy --strict`/`ruff` limpos

## Testes

- [x] Unit + integração (testcontainers Postgres 16 e MariaDB 11 reais) —
      caminho feliz, erro esperado, borda por item
- [x] Teste ponta a ponta Extrator → Sobrescrita →
      `AnalisadorDeMetricasDeColuna` contra Postgres real reproduzindo o
      crash original de `ARRAY`
- [x] `pytest` completo (unit + integration) verde antes do PR

## Status

Mergeada em `development` via PR (commit de merge `281eefc`, squash em
`main` no commit `3d6d829`). Branch `fix/57-corrige-array-postgres-e-json-mariadb`
removida (local e remoto) após o merge.

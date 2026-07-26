# Issue #76 — total_linhas exato + novas estratégias de amostragem

## Contexto

`total_linhas` é hoje estimativa de catálogo em ambos os motores
(`reltuples` no Postgres, `TABLE_ROWS` no MariaDB), nunca `COUNT(*)`. Isso
gera um `Aviso` de divergência sempre que a amostra (mesmo em
`percentual=100`) vem maior que a estimativa — comportamento esperado
(documentado desde a #63), mas confuso, especialmente em 100% onde se
espera exatidão.

Plano completo de implementação: `/home/dev/.claude/plans/sleepy-baking-yao.md`
(sessão de planejamento com Claude, 2026-07-25).

## Decisões tomadas na discussão prévia

> **`COUNT(*)` real descartado para `percentual<100`.** Dobraria o I/O — a
> amostragem já é full-scan nos dois motores (issue #56/NFR9) — sem ganho
> real pro caso de uso (catalogação de dados, não OLTP). Avaliação do
> engenheiro-de-dados: em `percentual=100` a leitura completa já acontece
> de qualquer forma, então usar `len(amostra)` como `total_linhas` nesse
> caso é exato e grátis; em `percentual<100`, `COUNT(*)` seria um segundo
> scan completo pago só pra exatidão que catalogação não exige.

> **Postgres troca `reltuples` por `COALESCE(NULLIF(n_live_tup, 0),
> reltuples)`**, sem custo adicional — `n_live_tup` é contador incremental
> por churn de DML, mais atual que `reltuples` (que só muda no `ANALYZE`).
> O `NULLIF(..., 0)` não estava no desenho original — foi adicionado depois
> de um teste de integração real (testcontainers, Postgres de verdade)
> quebrar: o stats collector é assíncrono e pode não ter processado um
> `ANALYZE` recente no instante da leitura, mesmo dentro do mesmo teste
> síncrono, fazendo `n_live_tup` ler 0 numa tabela não-vazia logo após
> `ANALYZE` — `reltuples`, por sua vez, é atualizado na própria transação do
> `ANALYZE`. Tratar `n_live_tup=0` como "ainda não reportado" e cair pra
> `reltuples` não perde nada em tabela genuinamente vazia (onde os dois
> seriam 0 de qualquer forma). Outras ressalvas conhecidas e aceitas: pode
> ficar incorreto após `pg_stat_reset()`, é local em réplicas físicas,
> tabela-mãe particionada não soma as partições automaticamente. MariaDB
> não tem fonte equivalente sem escrita/full-scan — mantém `TABLE_ROWS`
> como está (mesma categoria de trade-off já aceita na #35, só com margem
> maior).

> **Dispatch por `isinstance`/string entre estratégias de amostragem foi
> descartado (revisão bloqueante do arquiteto-de-software).** O Port
> `EstrategiaDeAmostragem` expunha só `percentual: float`, o que forçaria
> `FullScan` a "mentir" um percentual=100 fictício (viola Interface
> Segregation) e deixaria uma 3ª estratégia futura cair silenciosamente no
> branch errado do Extrator. Decisão: `percentual` vira `requisicao:
> RequisicaoDeAmostragem` — união fechada (`AmostragemProbabilistica |
> AmostragemIntegral`) — com `match`/`assert_never` nos Extratores. Uma
> estratégia não reconhecida vira erro de `mypy --strict`, não bug
> silencioso. Precedente aceito no próprio código: `mapear_tipo_postgres`/
> `mapear_tipo_mariadb` já exigem tocar os dois módulos por dialeto a cada
> categoria nova de `TipoDeDado` — mesmo formato de "raio de explosão
> proporcional e forçado pelo compilador".

> **Seed reprodutível fica só em `AmostragemProbabilistica`** (nunca no
> Port nem em `AmostragemIntegral`, que não tem o que reproduzir). Se o
> usuário não informar seed, o Extrator gera um antes de montar a query
> (nunca deixa o banco escolher em silêncio) e registra o valor efetivo em
> `MetadadosDeAmostra` — sem isso, reprodutibilidade não é verificável a
> partir do artefato gerado.

## Escopo desta issue

- [x] `AmostragemProbabilistica`/`AmostragemIntegral`/`RequisicaoDeAmostragem`
      (`domain/model/common/requisicao_de_amostragem.py`) — validação de
      `percentual` migrada de `PercentualDeLinhas.__init__` pra `Field`
      Pydantic, fonte única da regra
- [x] Port `EstrategiaDeAmostragem` troca `percentual: float` por
      `requisicao: RequisicaoDeAmostragem`; `PercentualDeLinhas` ganha
      `seed: int | None = None`
- [x] `FullScan` (`infrastructure/adapters/extractors/full_scan.py`) —
      nova estratégia, `requisicao` retorna `AmostragemIntegral()`; zero
      mudança nos Extratores (prova o ponto de OCP discutido no
      planejamento — o vocabulário já existia desde o Port)
- [x] `MetadadosDeAmostra` ganha `percentual`/`seed` efetivos (opcionais,
      `None` em `full_scan`)
- [x] Helpers compartilhados `seed_efetivo`/`construir_metadados_de_amostra`
      (mesmo padrão de `construir_colunas_fk.py`) — reuso real entre os
      dois Extratores, não decorativo
- [x] `ExtratorPostgres`: dispatch exaustivo (`match`/`assert_never`),
      `total_linhas=len(amostra)` em `AmostragemIntegral` (sem `Aviso` de
      divergência, sempre exato por definição), `n_live_tup` com fallback
      (validado contra Postgres real via testcontainers)
- [x] `ExtratorMariaDB`: dispatch exaustivo, mesma regra de
      `total_linhas=len(amostra)` em `AmostragemIntegral`; `TABLE_ROWS`
      mantido sem mudança de código
- [x] CLI (`registro/estrategias.py`): registra `FullScan` ("Tabela inteira
      (full scan)", sem prompt), prompt opcional de seed em
      `PercentualDeLinhas`, remove campo morto `classe_estrategia` de
      `EstrategiaRegistrada` e do parâmetro de `registrar_estrategia`
- [x] `GeradorContextoDeIA`/`GeradorMarkdown` passam a expor
      `percentual`/`seed` efetivos (JSON e rodapé do `.md`) — lacuna
      encontrada testando manualmente: sem isso, o campo adicionado em
      `MetadadosDeAmostra` não cumpria a própria razão de existir
      ("reprodutibilidade verificável a partir do artefato gerado", acima).
      `percentual`/`seed` já atravessavam Extraction → Curation → Analysis
      via `metadados_amostra`; só faltava os Geradores renderizarem.
- [x] `docs/low_level_design.md`/`docs/system_design_doc.md` atualizados
      (`full_scan` deixa de ser "extensão futura", `MetadadosDeAmostra` sem
      o `total_linhas` já removido na #9 mas ainda presente no
      `system_design_doc.md` desatualizado). `plan/tasks.md` não é tocado —
      seguindo o precedente das #56/#63/#67 (confirmado em
      `docs/engineer_guidelines.md`), issues após a #16 usam só este
      arquivo como checklist

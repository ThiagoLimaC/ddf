# Issue #7 — feat: Analysis Context

- [x] `domain/model/analysis.py` (arquivo único, mesmo padrão de `extraction.py`/`curation.py`)
  - `MetricaDeColuna` (BaseModel frozen) — `origem: str` — Value Object base
  - `MetricasBaseColuna(MetricaDeColuna)` — `percentual_nulo`, `percentual_unico`,
    `valores_frequentes`, `minimo`, `maximo`, `formato_detectado`;
    `origem = "AnalisadorDeMetricasDeColuna"`
  - `MetricaDeTabela` (BaseModel frozen) — `origem: str` — Value Object base
  - `MetricasBaseTabela(MetricaDeTabela)` — `completude: float`;
    `origem = "AnalisadorDeMetricasDeTabela"`
  - `ColunaAnalisada` — campos de `ColunaCurada` + `metricas: list[MetricaDeColuna]`
  - `TabelaAnalisada` — campos de `TabelaCurada` (sem `amostra`) +
    `metricas: list[MetricaDeTabela]` + `metadados_amostra`
  - `BancoAnalisado` — `tabelas: list[TabelaAnalisada]`; Pydantic puro
  - `ContextoDeAnalise` — `curado: BancoCurado`, `analisado: BancoAnalisado`;
    `arbitrary_types_allowed=True`
  - `iniciar_contexto(curado: BancoCurado) -> ContextoDeAnalise`

  > **Decisão:** pacote `domain/model/analysis/` com um arquivo por classe
  > (como sugerido no corpo da issue no GitHub) foi descartado — quebraria
  > consistência com `extraction.py`/`curation.py`, já mergeados como arquivo
  > único por Bounded Context.

  > **Renomeação decidida durante a implementação:** `MetricasBase` (nome do
  > low_level_design.md) foi renomeada para `MetricasBaseColuna`, e
  > `MetricasDeTabela` para `MetricasBaseTabela` — o nome original não deixava
  > claro que era a métrica *de coluna*, enquanto `MetricasDeTabela` já era
  > explícito, gerando assimetria. Propagado para `low_level_design.md`,
  > `tasks.md`, `engineer_guidelines.md`, `topics.md` e corpos das issues
  > #11-#15 no GitHub.

## Validações adicionais (mesmo critério da #6: achar brechas entre o snippet e regra de negócio real)

- [x] `MetricasBaseColuna.percentual_nulo` / `percentual_unico` — `Field(ge=0, le=100)`
      (já exigido explicitamente pela seção "Verificação" da task 2 em `plan/tasks.md`)
- [x] `MetricasBaseColuna.valores_frequentes` — limite de 10 itens (`Field(max_length=10)`)
- [x] `MetricasBaseTabela.completude` — `Field(ge=0, le=100)`
- [x] `ColunaAnalisada` — invariante de FK duplicada de `ColunaExtraida`/`ColunaCurada`
      (`chave_estrangeira=True` ⇔ `tabela_referenciada`/`coluna_referenciada` preenchidos)
- [x] `TabelaAnalisada` — nomes de `colunas` únicos (mesma regra de `TabelaCurada`)
- [x] `TabelaAnalisada` — `total_linhas >= 0` (mesma regra de `TabelaCurada`)
- [x] `BancoAnalisado` — `(nome_schema, nome_tabela)` únicos em `tabelas` (mesma regra de `BancoCurado`)

## Pendência registrada, não resolvida nesta issue

- Duplicidade de tipo na lista `metricas` (ex.: dois `MetricasBaseColuna` na mesma
  coluna, se um Analisador rodar duas vezes no `compor(...)`) — decidido não
  validar agora, pois é cenário de configuração errada do pipeline e o
  Analisador que causaria isso ainda não existe. Registrado como comentário
  na issue #11: https://github.com/ThiagoLimaC/ddf/issues/11#issuecomment-4894338786

## Testes (`tests/unit/domain/model/test_analysis.py`, agrupados por categoria)

- [x] Caminho feliz: criação válida de `MetricasBaseColuna`, `MetricasBaseTabela`,
      `ColunaAnalisada`, `TabelaAnalisada`, `BancoAnalisado`
- [x] Caminho feliz: `iniciar_contexto` a partir de `BancoCurado` de fixture —
      `analisado` nasce com `metricas=[]` em todas colunas/tabelas e campos de
      `ColunaCurada`/`TabelaCurada` copiados corretamente
- [x] Caminho feliz: `iniciar_contexto` com `BancoCurado` sem tabelas (achado na
      revisão pré-commit — cenário real de schema sem tabelas, não coberto
      pelo teste com fixture)
- [x] Erro esperado: mutação de `MetricasBaseColuna`/`MetricasBaseTabela`
      rejeitada (`frozen=True` — achado na revisão pré-commit: "regra mais
      importante" do `engineer_guidelines.md` nunca era exercitada por nenhum
      teste)
- [x] Erro esperado: `percentual_nulo`/`percentual_unico` fora de 0–100
- [x] Erro esperado: `completude` fora de 0–100
- [x] Erro esperado: `valores_frequentes` com mais de 10 itens
- [x] Erro esperado: FK inconsistente em `ColunaAnalisada`
- [x] Erro esperado: nomes de coluna duplicados em `TabelaAnalisada`
- [x] Erro esperado: `(schema, tabela)` duplicados em `BancoAnalisado`
- [x] Erro esperado: `total_linhas` negativo em `TabelaAnalisada`

  > Sem categoria de borda: seguindo o mesmo critério da #6, os limites
  > exatos (0.0/100.0, 10 itens) já são cobertos pela definição do próprio
  > `Field` e não representam um caso de negócio real e distinto — testá-los
  > separadamente seria artificial.

- [x] `mypy --strict` + `ruff` limpos

# Issue #11 — feat: AnalisadorDeMetricasDeColuna

## Decisões tomadas na discussão prévia (antes de implementar)

Diferente das issues anteriores, desta vez a "banca da verdade" (Arquiteto
de Software, Engenheiro de Dados, PO) foi acionada **antes** de qualquer
código, contra a especificação do `low_level_design.md`, não contra um diff
já pronto.

> **`percentual_unico` estava com viés estatístico real — nulos contavam
> como categoria distinta.** O Engenheiro de Dados testou empiricamente
> (Polars real): `[1, 1, None, 2, None].n_unique() == 3` — dois `null`s
> contam como 1 categoria própria. A fórmula original do LLD
> (`col.n_unique() / tamanho_amostra * 100`) inflava a unicidade de colunas
> com muitos nulos. **Decisão:** `col.drop_nulls().n_unique()` no numerador,
> mantendo `tamanho_amostra` (total, com nulos) no denominador — uma coluna
> 90% nula nunca aparenta "muito única" só porque os poucos valores
> presentes são todos distintos.

> **`value_counts()` também inclui uma linha `null`, sem `drop_nulls()`
> antes.** Mesmo achado do Engenheiro de Dados: sem excluir nulos,
> `valores_frequentes` podia trazer a string `"None"`/`"null"` como se fosse
> um valor de dado real. **Decisão:** `drop_nulls()` antes de
> `value_counts()`.

> **Divisão por zero não resolvida na fórmula publicada para
> `tamanho_amostra == 0`**, embora o caso já estivesse listado nos critérios
> de aceite da issue. **Decisão:** guarda explícita — `tamanho_amostra == 0`
> retorna métricas vazias (`0.0`/`None`/`[]`) sem tentar dividir, antes de
> qualquer cálculo Polars.

> **`valores_frequentes` descartava a contagem que `value_counts()` já
> calcula de graça.** Achado do Engenheiro de Dados, endossado como "momento
> certo pra decidir" pelo Arquiteto de Software (Value Object imutável, sem
> consumidor ainda — mudar o shape depois que Geradores existirem seria
> migração coordenada). **Decisão:** `MetricasBaseColuna.valores_frequentes`
> muda de `list[str]` para `list[tuple[str, int]]`, top 10 por
> `(count desc, valor asc)` — desempate determinístico, já que
> `value_counts(sort=True)` não garante ordem estável entre valores com a
> mesma contagem.

> **Threshold de 80% para `formato_detectado` não considerava contagem
> absoluta de valores não-nulos.** Uma coluna com 3 valores não-nulos
> batendo 100% não deveria acionar `formato_detectado` com a mesma confiança
> que 1000 valores a 80% — "falsa confiança" em colunas majoritariamente
> nulas com poucos valores presentes. **Decisão:** exigir também um mínimo
> absoluto de 20 valores não-nulos, além do threshold percentual.

> **Regex de email tinha falso negativo comum em bases brasileiras.** `r'^[\w.+-]+@[\w-]+\.[a-z]{2,}$'`
> não casa domínio com subdomínio/TLD composto (`user@mail.empresa.com.br`,
> `user@sub.dominio.co.uk`) porque `[\w-]+` não permite ponto antes do TLD —
> justamente o caso mais comum em e-mail corporativo real. **Decisão:**
> `r'^[\w.+-]+@[\w.-]+\.[a-z]{2,}$'` com `re.IGNORECASE` (regex original
> também não tinha, e TLD em maiúsculo é comum).

> **Precedência entre formatos que casam mais de um regex não estava
> definida** (ex.: um CEP também casa o regex de `phone` frouxo). **Decisão:**
> ordem fixa de checagem `email → cpf → cnpj → phone → cep` (mesma ordem da
> tabela do LLD) — primeiro que atinge o threshold vence. Simples,
> determinístico, sem heurística extra de desambiguação.

> **Formatos são intencionalmente Brasil-específicos** (CPF/CNPJ/CEP, DDD
> nacional no `phone`) — decisão de produto explícita, não lacuna de
> generalização. Documentado aqui para quem avaliar cobertura internacional
> no futuro.

`docs/low_level_design.md` e `plan/tasks.md` (seção 5) já foram atualizados
com essas decisões antes do código.

## Escopo desta issue

- [x] `domain/model/analysis.py` — `MetricasBaseColuna.valores_frequentes`
      de `list[str]` para `list[tuple[str, int]]`
- [x] `infrastructure/adapters/analyzers/detector_de_formato.py` —
      `detectar_formato()`, função pura (sem Polars), testada isoladamente
- [x] `infrastructure/adapters/analyzers/analisador_de_metricas_de_coluna.py`
      — `AnalisadorDeMetricasDeColuna(Analisador)`: `produz =
      [MetricasBaseColuna]`, `requer = []`, cálculo via Polars por coluna,
      libera `tabela.amostra` após cada tabela, `Aviso` por coluna se
      `tamanho_amostra < 100`, `Falha` defensiva se `curado`/`analisado`
      saírem de sincronia
- [x] Testes unit (feliz/erro/borda) para `detector_de_formato` e
      `AnalisadorDeMetricasDeColuna` (25 testes novos)
- [x] `mypy --strict src` (45 arquivos, 0 erros) e `ruff check .` limpos

## Testes

- [x] `tests/unit/domain/model/test_analysis.py` — ajustado para o novo
      shape de `valores_frequentes` (2 pontos)
- [x] `tests/unit/infrastructure/adapters/analyzers/test_detector_de_formato.py`
      — feliz (cada formato, incl. e-mail com subdomínio/TLD composto e
      precedência cpf/phone), borda (abaixo do threshold, menos de 20
      valores, lista vazia)
- [x] `tests/unit/infrastructure/adapters/analyzers/test_analisador_de_metricas_de_coluna.py`
      — conformidade ao Port, cálculo completo com detecção de e-mail, amostra
      liberada após a tabela (feliz); `curado`/`analisado` fora de sincronia
      (erro esperado); `tamanho_amostra=0` sem dividir por zero, coluna
      inteiramente nula, nulos excluídos de `percentual_unico`/
      `valores_frequentes`, `Aviso` de amostra pequena com origem correta,
      desempate de `valores_frequentes` por valor crescente, coluna VARCHAR
      com poucos não-nulos não aciona formato, coluna INTEGER nunca tenta
      detectar formato (borda)
- [x] Verificação completa: `pytest tests/unit` (200 passed, +28 desde a
      #35, incl. 2 testes da segunda rodada da banca + 1 da terceira), `mypy
      --strict src` (45 arquivos, 0 erros) e `ruff check .` sem erros

## Validação empírica do mínimo absoluto de 20 valores não-nulos

Pergunta do PO na segunda rodada: o corte de 20 foi validado empiricamente,
ou é um número redondo? Resposta: calculado agora via intervalo de
confiança de Wilson (95%) para uma proporção observada de 80%:

| n (valores não-nulos) | IC 95% do % de match real |
|---|---|
| 10 | [49.0%, 94.3%] — limite inferior abaixo de 50%, "maioria" não é defensável |
| 15 | [54.8%, 93.0%] — margem apertada |
| **20** | **[58.4%, 91.9%]** — pior caso ainda claramente majoritário |
| 30 | [62.7%, 90.5%] |
| 100 | [71.1%, 86.7%] |

`n=20` é o ponto em que, mesmo no pior cenário do IC 95%, o verdadeiro
percentual de match continua acima de ~58% — folga suficiente para chamar o
formato de "dominante" sem exigir amostras grandes demais para uma
ferramenta leve de profiling. Não é mais um número arbitrário.

## Achados da banca de revisão (Arquiteto de Software + PO + Engenheiro de Dados)

### Primeira rodada — sobre a especificação, antes do diff

Ver "Decisões tomadas na discussão prévia" acima — todos os achados do
Engenheiro de Dados foram incorporados antes de escrever código. Arquiteto
de Software e PO: **Aprovado**, sem bloqueantes. Recomendações estruturais
do Arquiteto (módulo `detector_de_formato.py` separado da orquestração do
Adapter, `_liberar_amostra` como função nomeada, não inline) incorporadas
ao design.

### Segunda rodada — sobre o código já escrito

Veredito unânime: **Aprovado com ressalvas**, nenhum bloqueante. Achados
incorporados:

> **Guarda de invariante assimétrica entre nível tabela e nível coluna
> (Arquiteto).** `__call__` só validava `len(curado.tabelas) !=
> len(analisado.tabelas)` com `Falha`; um desalinhamento no nível de coluna
> estouraria `ValueError` cru do `zip(..., strict=True)`. Hoje inatingível
> (`iniciar_contexto` sempre monta 1:1), mas inconsistente. **Corrigido:**
> guarda equivalente por tabela (`len(tabela_curada.colunas) !=
> len(tabela_analisada.colunas)` → `Falha`) antes de processar cada tabela.

> **`__call__` com 4 responsabilidades acumuladas (Arquiteto).** Sugestão de
> extrair o processamento por tabela, já que este é o primeiro Analisador e
> serve de modelo para os próximos (ex. `AnalisadorDeMetricasDeTabela`).
> **Corrigido:** `_processar_tabela(tabela_curada, tabela_analisada) ->
> list[Aviso]` extraída; `__call__` ficou só com a guarda de invariante, o
> loop de tabelas e a montagem do `Sucesso` final.

> **`_top_valores_frequentes` denso (Arquiteto).** `.sort(...).head(10)`
> encadeado com `list(zip(...))` numa linha só, num trecho cuja lógica de
> desempate já é sutil. **Corrigido:** quebrado em passos nomeados
> (`contagens`, `topo`, `valores`, `frequencias`).

> **Guarda de amostra vazia não cobria amostra presente com 0 linhas
> enquanto `tamanho_amostra` reporta valor positivo (Engenheiro de Dados,
> validado empiricamente com Polars real).** Divergência upstream (ex.: bug
> de sampling gravando metadados errados) produzia métrica factualmente
> errada e silenciosa (`percentual_nulo=0.0` como se a amostra tivesse dado
> real), porque a guarda só checava `amostra is None or tamanho_amostra ==
> 0`. **Corrigido:** guarda agora inclui `amostra.height == 0`. Teste novo:
> `test_amostra_presente_mas_vazia_diverge_de_tamanho_amostra_positivo`.

> **Cobertura estatística faltando um caso intermediário de
> `percentual_nulo` (Engenheiro de Dados).** Só os extremos 0%/100% eram
> testados — um bug sutil de fórmula (denominador errado, `*100`
> esquecido) passaria despercebido. **Corrigido:** teste novo
> `test_percentual_nulo_intermediario` (30 nulos / 100 → 30.0%).

### Terceira rodada — achado do Engenheiro de Dados corrigido a pedido do usuário

> **`NaN` em colunas FLOAT não era tratado como nulo pelo Polars — corrigido.**
> Validado empiricamente (Polars real): `null_count()` não conta `NaN`, e
> `n_unique()`/`value_counts()` tratam `NaN` como categoria própria,
> diferente de `null`. Numa coluna FLOAT com `NaN`, isso subestimava
> `percentual_nulo` e inflava `percentual_unico`/`valores_frequentes` com
> uma entrada "NaN" fantasma. **Corrigido:** `_calcular_metricas_coluna`
> normaliza `NaN`→`null` via `serie.fill_nan(None)` antes de qualquer
> cálculo, condicionado a `serie.dtype.is_float()` — testado empiricamente
> que `fill_nan` **não** é no-op seguro em toda coluna: em `Utf8`/string
> ele lança `InvalidOperationError` (`is_not_nan` não suportado pra `str`),
> por isso a checagem de dtype é obrigatória, não defensiva por excesso de
> zelo. Teste novo: `test_coluna_float_trata_nan_como_nulo` (mistura NaN +
> None + valores reais, confere `percentual_nulo`, `percentual_unico`,
> `valores_frequentes`, `minimo`/`maximo`).

## Pendências para próximas issues (não resolvidas aqui)

- `AnalisadorDeMetricasDeTabela` (próxima sub-issue da Fase 5).
- `validar_dependencias`/`FONTES_REGISTRADAS`/CLI (issue #16, Fase 7).
- Qualquer Gerador consumindo `MetricasBaseColuna` (Fase 6) — inclusive
  decidir como `valores_frequentes: list[tuple[str, int]]` aparece no
  Markdown/dbt/IA gerados, e como comunicar ao usuário final a limitação
  regional (Brasil-específica) de `formato_detectado`.

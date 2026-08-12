# Issue #12 — feat: AnalisadorDeMetricasDeTabela

## Decisões tomadas na discussão prévia (antes de implementar)

Sem rodada de banca (Arquiteto/Engenheiro de Dados/PO) para esta issue — o
escopo é pequeno e direto o suficiente (uma média sobre métricas já
calculadas, sem Polars, sem I/O) para resolver as ambiguidades diretamente
com o usuário. Três decisões, registradas antes do código:

> **Tabela com `colunas=[]` — completude é média de um conjunto vazio,
> indefinida.** Alternativas consideradas: `Falha` (trata como violação de
> invariante) ou `completude=100.0` (vácuo-verdadeiro). **Decisão:**
> `completude=100.0` foi descartada por dar falsa confiança ("tabela
> perfeitamente completa" sobre uma tabela sem nenhuma coluna); `Falha` foi
> descartada por ser overkill para um caso que não impede o cálculo.
> **`completude=0.0`** — tratamento mais conservador para quem consome a
> métrica depois, sem interromper o pipeline.

> **Coluna com mais de uma `MetricasBaseColuna` em `metricas`** (`list[
> MetricaDeColuna]` comporta N métricas de N Analisadores, inclusive o mesmo
> Analisador rodado 2x sobre o mesmo `ContextoDeAnalise`). O
> `low_level_design.md` sugere `next(m for m in col.metricas if isinstance(
> m, MetricasBaseColuna), None)` para Geradores, que silenciosamente usaria
> a primeira ocorrência. **Decisão:** `Falha` em vez de `next()` — duplicata
> indica execução fora de ordem/Analisador reexecutado por engano; mascarar
> com a primeira ocorrência esconderia o bug em vez de expô-lo.

> **Escopo da `Falha` defensiva quando `MetricasBaseColuna` está ausente.**
> Alternativas: `Falha` imediata (interrompe tudo) vs. acumular erros por
> tabela e continuar processando as demais. **Decisão:** `Falha` imediata,
> mesmo padrão do guard de sincronia do `AnalisadorDeMetricasDeColuna`
> (issue #11) e do próprio `compor()` (para no primeiro `Falha`, sem
> acumular parcialmente).

`docs/low_level_design.md` (seção `AnalisadorDeMetricasDeTabela`) já
descrevia o comportamento no nível de especificação; as três decisões acima
resolvem lacunas de borda que a especificação não detalhava.

## Escopo desta issue

- [x] `infrastructure/adapters/analyzers/analisador_de_metricas_de_tabela.py`
      — `AnalisadorDeMetricasDeTabela(Analisador)`: `produz =
      [MetricasBaseTabela]`, `requer = [MetricasBaseColuna]`; calcula
      `completude` por tabela como média de `(100 - percentual_nulo)` das
      colunas; sem Polars (só itera `list[ColunaAnalisada]`/
      `list[MetricaDeColuna]` já calculados)
- [x] `_completude_da_tabela` extraída como helper puro, testável isolado —
      mesmo padrão de `_processar_tabela` do #11
- [x] Testes unit (feliz/erro/borda) cobrindo as 3 decisões acima
- [x] `mypy --strict src` (46 arquivos, 0 erros) e `ruff check .` limpos

## Testes

- [x] `tests/unit/infrastructure/adapters/analyzers/test_analisador_de_metricas_de_tabela.py`
      (11 testes): conformidade ao Port `Analisador`; cálculo correto da
      média com colunas de `percentual_nulo` distintos; múltiplas tabelas
      processadas com `completude` independente cada; `Falha` quando
      `MetricasBaseColuna` está ausente numa coluna; `Falha` quando está
      duplicada numa coluna; `Falha` na primeira tabela interrompe antes de
      processar a segunda (nenhuma métrica é acrescentada a ela); tabela sem
      colunas → `completude=0.0`; divisão não exata (200/3) preserva
      precisão de ponto flutuante, sem `round()`/truncamento; todas as
      colunas sem nulo → `completude=100.0`; todas as colunas 100% nulas →
      `completude=0.0`; Open/Closed — `compor(AnalisadorDeMetricasDeColuna(),
      AnalisadorDeMetricasDeTabela())` encadeados de ponta a ponta (amostra
      Polars real) sem exigir nenhuma edição no Analisador da #11
- [x] Verificação completa: `pytest tests/unit` (211 passed, +11 desde a
      #11), `mypy --strict src` (46 arquivos, 0 erros) e `ruff check .` sem
      erros

## Sem Aviso emitido

Ao contrário do `AnalisadorDeMetricasDeColuna` (que emite `Aviso` por amostra
pequena), este Analisador não emite nenhum `Aviso`: nada no escopo da issue
pede um, e não há sinal de qualidade de dado equivalente a "amostra pequena"
neste nível — a avaliação de tamanho de amostra já foi feita e avisada pelo
Analisador anterior.

## Achados da banca de revisão (Arquiteto de Software + Engenheiro de Dados + PO)

Banca acionada sobre o código já escrito (não sobre a especificação, como
na #11). Veredito unânime: **Aprovado / Aprovado com ressalvas**, nenhum
bloqueante.

> **Média não ponderada de `completude` tem viés estatístico conhecido
> (Engenheiro de Dados, endossado pelo PO).** Uma coluna crítica quase toda
> nula é diluída por várias colunas perfeitas (e o inverso ocorre em
> tabelas com poucas colunas). Comparação com dbt docs/Great
> Expectations/DataHub: é a mesma escolha padrão de mercado — média simples
> por coluna, agregação de tabela deixada para quem consome. Não é erro de
> implementação, é escolha de produto sobre "que número expor primeiro".
> **Decisão do usuário:** a completude agregada da tabela deve, na Fase 6
> (Geradores), **sempre vir ao lado do detalhamento por coluna** — nunca
> como número isolado. Exemplo concreto que motiva a decisão: uma tabela
> com 10 colunas 100% preenchidas e 1 coluna crítica 90% nula tem
> `completude = (10×100 + 10) / 11 ≈ 90.9%` — parece "quase perfeita" mesmo
> com uma coluna praticamente inutilizável. Só o número agregado esconde
> esse problema; ao lado do detalhamento por coluna (`percentual_nulo` de
> cada uma, já disponível em `ColunaAnalisada.metricas`), o problema fica
> visível. **Ação:** nenhuma mudança de código aqui — dado já está
> disponível na arquitetura (`ColunaAnalisada.metricas` não é descartado);
> fica registrado como requisito de exibição para quando o Gerador
> Markdown/dbt/IA for especificado.

> **`completude=0.0` de "tabela sem colunas" é indistinguível de
> `completude=0.0` de "tabela com dados 100% nulos" (PO).** Mesma
> observação do ponto acima: resolvida pela mesma decisão (completude
> sempre acompanhada do detalhamento por coluna — uma tabela sem colunas
> não tem colunas para detalhar, o que já desambiguiza os dois casos na
> apresentação).

> **Helper genérico `filtrar_por_tipo(lista, Tipo)` para substituir o
> list comprehension com `isinstance` em `_completude_da_tabela`
> (Arquiteto).** Hoje é só um Analisador filtrando `MetricasBaseColuna` de
> `list[MetricaDeColuna]`; extrair um helper compartilhado agora seria
> abstração prematura (regra das 3 repetições ainda não atingida — só há 1
> ocorrência deste padrão no código, a do próprio #11 usa acesso direto por
> já saber que só há uma métrica). **Decisão:** não implementar agora,
> registrar como pendência explícita para quando um 3º Analisador de coluna
> aparecer e o mesmo filtro se repetir.

> **Falta teste de Open/Closed explícito provando que este Analisador se
> encaixou sem editar o anterior (Arquiteto).** **Corrigido:**
> `test_compoe_com_analisador_de_metricas_de_coluna_sem_editar_nenhum_dos_dois`
> — encadeia `AnalisadorDeMetricasDeColuna` e `AnalisadorDeMetricasDeTabela`
> via `compor()` real, com amostra Polars real, provando que os dois só se
> comunicam pelo Port `Analisador` e por `ColunaAnalisada.metricas`.

> **Falta teste de precisão de ponto flutuante para divisão não exata
> (Engenheiro de Dados).** **Corrigido:**
> `test_completude_com_divisao_nao_exata_preserva_precisao_de_ponto_flutuante`
> — 3 colunas com nulos `[0%, 0%, 100%]` geram `completude = 200/3 =
> 66.666...`, confirmando que o código não arredonda nem trunca (decisão de
> formatação/casas decimais fica para o Gerador, Fase 6).

## Pendências para próximas issues (não resolvidas aqui)

- Wiring no `compor()` real do pipeline de análise — ainda não existe um
  ponto de entrada que encadeie `AnalisadorDeMetricasDeColuna` →
  `AnalisadorDeMetricasDeTabela` fora dos testes; isso é escopo da CLI/wizard
  (issue #16, Fase 7 do `plan/global.md`).
- Qualquer Gerador consumindo `MetricasBaseTabela` (Fase 6) —
  **`completude` deve ser exibida sempre ao lado do detalhamento por
  coluna, nunca como número isolado** (ver achado da banca acima); decidir
  também como comunicar a distinção "tabela sem colunas" vs. "tabela com
  dados 100% nulos" na apresentação.
- Helper genérico `filtrar_por_tipo(lista, Tipo)` para filtrar Value
  Objects por `isinstance` em `list[MetricaDeColuna]`/`list[MetricaDeTabela]`
  — só extrair quando um 3º Analisador repetir o mesmo padrão (regra das 3
  repetições).

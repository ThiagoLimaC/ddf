# Issue #115 — perf: detectar_formato roda sobre 100% da amostra — introduzir sub-amostragem para tabelas grandes

## Contexto

Achado do engenheiro de dados numa investigação de lentidão na fase de
Análise, junto da investigação de streaming de extração (#114), com banca
multi-agente (engenheiro-de-dados + arquiteto-de-software, 2026-08-03),
contra um schema Postgres real de produção (122 tabelas).

Em `analisador_de_metricas_de_coluna.py:189`, `detectar_formato`
(`detector_de_formato.py`) rodava sobre **100% dos valores não-nulos da
amostra** de toda coluna VARCHAR/TEXT — convertendo a Series Polars inteira
para lista Python (`.to_list()`), gerando `str(valor)` por elemento, e
rodando até 5 regex num laço Python puro, sem soltar o GIL, sem
paralelismo. Para uma tabela outlier de tamanho (caso real: 411K linhas de
amostra a 10%, ou 4M+ em `TabelaInteira`), isso era potencialmente 5 × N
operações de regex Python single-thread — explicação mais direta para "a
análise também demorou mais" reportado no teste do usuário.

Não é só custo: o threshold de decisão de `formato_detectado` já é 80% de
match **e** mínimo absoluto de 20 valores não-nulos. Rodar essa checagem
sobre a população inteira da amostra não aumenta a confiabilidade da
decisão além de um certo ponto — mesmo tipo de correção que
`TABLESAMPLE`/`PercentualDeLinhas` já aplicam na extração (amostrar a
entrada de uma operação cara, sem perder a garantia estatística que a
métrica precisa entregar).

Plano completo de implementação: `/home/dev/.claude/plans/misty-wishing-dusk.md`
(sessão de planejamento com Claude, 2026-08-04). Plano revisado e
**aprovado com ressalvas** pela banca (arquiteto-de-software,
engenheiro-de-dados, po-revisor) antes da implementação — ressalvas
incorporadas nas decisões abaixo.

## Decisões tomadas na discussão prévia

> **Sub-amostragem na Series Polars, dentro do Analisador — não dentro de
> `detectar_formato`.** `detectar_formato()` continua recebendo `list[str]`
> sem mudança de assinatura; a sub-amostragem acontece em
> `analisador_de_metricas_de_coluna.py` (que já importa `polars`), antes do
> `.to_list()`. Resolve de uma vez o custo de conversão da população
> inteira para lista Python **e** o custo do laço de regex, sem vazar
> Polars para `comum/detector_de_formato.py`. Confirmado pelo
> arquiteto-de-software.

> **Seed fixo, não derivado do seed de extração.** `MetadadosDeAmostra.seed`
> é `None` em `TabelaInteira` (não seria universal) e não há campo em
> `MetricasBaseColuna` para registrar um seed gerado — replicar
> `seed_efetivo()` aqui geraria uma sub-amostra "aleatória mas não
> registrada", pior que hoje. Constante fixa dá determinismo total sem
> inventar novo campo de métrica (violaria "Métricas como Value Objects").
> Confirmado pelo arquiteto-de-software e pelo engenheiro-de-dados.

> **Sem helper extraído para a lógica de sub-amostragem.** Só 1 call site,
> nenhuma regra arquitetural exige isolamento, testável via o Analisador
> público — extrair seria a indireção decorativa que o projeto já rejeita.
> Ressalva do arquiteto-de-software.

> **Teto de 2000 valores não-nulos**, com justificativa estatística
> documentada em código: margem de erro do teste de proporção em p≈0.8 (o
> threshold), IC 95%: `1.96 * sqrt(0.8*0.2/2000) ≈ ±1.75%` — abaixo do teto
> de 3% pedido na issue. `with_replacement=False` confirmado como escolha
> correta para estimar proporção populacional. Validado pelo
> engenheiro-de-dados.

## Escopo desta issue

- [x] `detector_de_formato.py`: nova constante pública `TETO_SUBAMOSTRA =
      2000`, com justificativa estatística em docstring
- [x] `analisador_de_metricas_de_coluna.py`: sub-amostragem determinística
      (seed fixo `_SEED_SUBAMOSTRA_FORMATO`, `with_replacement=False`) da
      Series Polars antes de `.to_list()`, só quando `nao_nulos.len() >
      TETO_SUBAMOSTRA`; abaixo do teto, comportamento inalterado
- [x] `docs/low_level_design.md`: seção `AnalisadorDeMetricasDeColuna`
      (tabela "Detecção de formato") documentando o teto e a sub-amostragem
- [x] `mypy --strict`/`ruff` limpos

## Fora de escopo

- Paralelizar a checagem de regex (`ProcessPoolExecutor`) — a
  sub-amostragem já resolve o custo de forma mais barata, sem complexidade
  de paralelismo adicional
- Mudar o threshold de 80% ou o mínimo de 20 valores não-nulos já
  existentes
- Tornar `TETO_SUBAMOSTRA` configurável via CLI/env var — sugestão
  nice-to-have do po-revisor, não bloqueante; 2000 é bem fundamentado, e se
  algum motor real exigir ajuste fino no futuro é issue separada

## Testes

- [x] Amostra grande ativa sub-amostragem e ainda detecta formato
      corretamente (ex. 5.000 e-mails válidos, sem ambiguidade de %)
- [x] Amostra no teto ou abaixo mantém comportamento atual (roda sobre a
      amostra inteira)
- [x] Determinismo entre execuções repetidas sobre a mesma amostra grande
- [x] Estabilidade da decisão perto do limiar, com proporção sintética
      afastada da fronteira (não é possível testar de forma não-flaky
      exatamente em 80% ± 1.75% com dado sintético determinístico) —
      ressalva convergente do engenheiro-de-dados e do po-revisor:
      `formato_detectado` alimenta a geração de teste dbt `matches_format`
      (issue #90), então um flip perto do threshold vira teste dbt falho
      contra dado real
- [x] `mypy --strict`/`ruff` limpos
- [x] `pytest` completo (unit) verde

## Status

Implementado em `perf/115-detectar_formato-roda-sobre-100-da-amostra`.
Falta abrir o PR pra `development`.

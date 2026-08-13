# Issue #141 — feat: sinaliza confiança estatística das métricas e corrige tabela particionada

## Contexto

Mesma auditoria de fechamento de v1 da #140 — achados que fazem os artefatos
(Markdown/dbt/contexto de IA) afirmarem algo sobre o dado sem informação
suficiente pra sustentar a afirmação. Ambos os achados abaixo foram
encontrados de forma **convergente por lentes diferentes** (o sinal de
confiança foi apontado, de forma independente e sem coordenação entre si,
pelo arquiteto-de-software, pelo engenheiro-de-dados e pelo PO — sinal forte
de que é real) ou validado empiricamente contra Postgres real (tabela
particionada).

## Decisões tomadas na discussão prévia (antes de implementar)

> **Sinal de confiança: resolver antes da v1, não aceitar como débito** —
> decisão explícita do usuário. É o contrato que todo Analisador futuro vai
> herdar: se `MetricasBaseColuna` não carrega esse sinal agora, cada novo
> Analisador reintroduz o mesmo silêncio.

> **Tabela particionada: só a tabela-mãe, com `total_linhas` agregado (soma
> real das partições)** — decisão explícita do usuário, depois de entender o
> conceito (tabela particionada = uma única tabela lógica dividida
> internamente em sub-tabelas físicas, sempre endereçada pelo nome da mãe em
> queries reais). Trata como uma única tabela lógica, do jeito que qualquer
> ferramenta de catálogo trataria e do jeito que o usuário realmente consulta
> o banco — as partições individuais somem da listagem/artefatos.

## Achados desta issue, com evidência

### 1. Nenhum sinal de baixa confiança estatística no artefato exposto

**Arquivos:**
`analyzers/analisador_de_metricas_de_coluna.py:22,95-108,151-153`;
`generators/contexto_de_ia/_serializacao.py:79-95,160-163`;
`generators/markdown/_filtros.py:221-290`

O que existe hoje: piso de 100 linhas (`_TAMANHO_AMOSTRA_MINIMO_AVISO`,
duplicado em mais duas constantes — ver #142) usado como **gate** em
`accepted_values`, `not_null_proportion`, `unique_percentage_at_least`, e como
**Aviso agregado de terminal** no Analisador; e a flag `amostra_vazia` (0
linhas) no `ai_context.json`/Markdown. O que **não** existe: nenhum campo no
artefato dizendo "esta métrica veio de N linhas" ou "esta métrica tem baixa
confiança".

**Cenário concreto:** banco com 200 tabelas, 60 delas de configuração/lookup
com 20-80 linhas. Amostragem 10% (default) → 2-8 linhas amostradas. O
`ai_context.json` de cada uma carrega `"percentual_nulo": 0.0,
"percentual_unico": 100.0` — sintaticamente idêntico ao de uma tabela de 5M
linhas lida integralmente. O Aviso agregado no terminal ("Amostra pequena em
60 de 200 tabelas") **não viaja com o artefato**, e o artefato é justamente o
que o agente de IA e o revisor de PR vão ler meses depois.
`formato_detectado` já tem piso próprio (20 valores não-nulos,
`detector_de_formato.py:15`) — é o único caso hoje com esse tipo de guarda.

**Por que resolver agora, não depois:** todo Analisador futuro vai herdar o
mesmo silêncio se `MetricasBaseColuna` não carregar esse sinal.

**Correção:** adicionar sinal de confiança como **novo tipo** (respeitando a
regra "nova métrica = novo tipo" do `CLAUDE.md` — não um campo solto em
`ColunaAnalisada`/`TabelaAnalisada`), populado pelo `AnalisadorDeMetricasDeColuna`
junto de `MetricasBaseColuna`, consumido pelos 3 Geradores:
- Markdown: nota visível junto da métrica (mesmo padrão já usado pra "0.00%
  (garantido pelo schema)" e "sem evidência (amostra vazia)")
- dbt: usado como critério adicional (ou reaproveitando o piso já existente,
  ver #140 item 3) para decidir severidade/supressão de sugestão
- Contexto de IA: campo explícito no JSON por coluna, não só o binário
  `amostra_vazia`

Definir o critério de "baixa confiança" reaproveitando o mesmo piso já usado
em outros lugares do código (100 linhas) em vez de inventar um novo número —
ver #142 sobre consolidar as 3 constantes duplicadas de piso 100 nesta mesma
oportunidade, se fizer sentido durante a implementação.

### 2. Tabela particionada (Postgres): pai e partições viram tabelas independentes

**Arquivos:** `extractors/postgres/_queries.py:12-17` (`_LISTAR_TABELAS_SQL`) e
`:83-98` (`_TOTAL_LINHAS_SCHEMA_SQL`)

Validado em Postgres 15 real, tabela `p` particionada por range com 1000
linhas na partição `p1`:

```
information_schema.tables → p (BASE TABLE), p1 (BASE TABLE)
_TOTAL_LINHAS_SCHEMA_SQL  → p: est=0 (n_live_tup=0, reltuples=-1) | p1: est=1000
```

Consequências encadeadas, em produção real (tabela de eventos/faturamento
particionada por mês, 24-60 partições):
1. O lote extraído tem N+1 tabelas; a mãe amostra o mesmo dado das filhas →
   `dbt run` cria 61 models, um deles sendo a união dos outros 60. Quem
   consumir o staging conta tudo em dobro.
2. O pai dispara `Aviso` de "amostra maior que `total_linhas`"
   (`construir_metadados_de_amostra.py:82-92`) em *toda* execução — ruído
   sistemático, não sinal.
3. Markdown e `ai_context.json` documentam 61 "tabelas", com a mãe declarando
   `total_linhas: 0` e uma amostra não-vazia — um agente de IA lendo isso
   conclui que a tabela está vazia quando na verdade tem os dados de todas
   as partições disponíveis via consulta normal.

O paralelismo intra-tabela (#126) já sabe distinguir `relkind='p'`
(`_TABELAS_PARTICIONADAS_SCHEMA_SQL`), então o dado necessário já é extraído
— só não é usado na listagem nem no `total_linhas`.

**Correção (decisão já fechada, ver acima):** tratar como uma única tabela
lógica:
- `listar_tabelas`: excluir partições filhas da listagem (usar
  `pg_inherits` para identificar quais entradas de `information_schema.tables`
  são partições de outra tabela do mesmo schema)
- `_TOTAL_LINHAS_SCHEMA_SQL`: para a tabela-mãe, somar `total_linhas`
  estimado de todas as suas partições reais (via `pg_inherits` +
  `n_live_tup`/`reltuples` de cada uma), em vez de usar a estimativa
  (sempre ~0) do próprio pai
- Amostra da mãe continua vindo de uma leitura normal contra o nome da
  tabela-mãe (o Postgres já roteia sozinho pras partições certas)

## Escopo desta issue

- [ ] Novo tipo de métrica/campo de confiança em `domain/model/analysis.py`
      (`MetricasBaseColuna` ou tipo próprio) — critério de "baixa confiança"
      alinhado ao piso de amostra já usado no projeto
- [ ] `AnalisadorDeMetricasDeColuna` — popula o sinal de confiança
- [ ] `GeradorMarkdown`/`GeradorDbt`/`GeradorContextoDeIA` — consomem o sinal
      (nota visível no Markdown, campo explícito no JSON, uso no dbt)
- [ ] `extractors/postgres/_queries.py` — `_LISTAR_TABELAS_SQL` exclui
      partições filhas (via `pg_inherits`); `_TOTAL_LINHAS_SCHEMA_SQL` agrega
      `total_linhas` das partições reais na tabela-mãe
- [ ] `mypy --strict`/`ruff` limpos

## Testes

- [ ] Unit: coluna com amostra muito pequena vs. muito grande — sinal de
      confiança presente e correto nos 3 Geradores
- [ ] Integração (testcontainers, Postgres real): tabela particionada com 2+
      partições reais — listagem mostra só a mãe, `total_linhas` bate com a
      soma real das partições, amostra vem da tabela-mãe normalmente
- [ ] Regressão: suíte de Extractors/Geradores segue verde (ajustar fixtures
      que hoje simulam tabela particionada como entrada separada, se houver)

## Verificação final

- [ ] `mypy --strict src` + `ruff check .` limpos
- [ ] `pytest tests/unit` + `pytest tests/integration` (Postgres real com
      tabela particionada de verdade) verdes
- [ ] Geração manual de artefato (Markdown/dbt/JSON) contra fixture com
      amostra pequena e fixture com tabela particionada, inspeção visual

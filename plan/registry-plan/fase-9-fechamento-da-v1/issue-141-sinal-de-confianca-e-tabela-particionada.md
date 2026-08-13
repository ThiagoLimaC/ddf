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

## Rodada de planejamento detalhado (pré-implementação)

O desenho abaixo foi detalhado e revisado por uma banca em paralelo
(arquiteto-de-software, engenheiro-de-dados, po-revisor) antes de codar —
aprovação com ressalvas dos três, achados complementares (sem divergência
real). Duas tensões entre o escopo original acima e os achados da banca
foram levadas ao usuário e resolvidas; o escopo abaixo já reflete a decisão
final.

### Decisões desta rodada (além das duas já travadas acima)

- **Critério de confiança não reaproveita o piso binário de 100 linhas**
  sugerido originalmente acima — o engenheiro de dados validou que um corte
  só por `tamanho_amostra` (ignorando `total_linhas`, usando a proporção
  observada) colapsa para `SE=0` numa coluna PK/UNIQUE
  (`percentual_unico=100%` zera a variância `p(1-p)` para qualquer `n`),
  classificando como confiável exatamente o cenário que a issue quer
  sinalizar como não confiável. Fórmula final: erro-padrão **conservador**
  (`p=0,5` fixo, não a proporção observada) com correção de população
  finita, 95% de margem:

  ```
  SE = sqrt(0.25 / n × (N - n) / (N - 1))
  margem_de_erro_pp = 1.96 × SE × 100
  ```

  com `n = tamanho_amostra`, `N = total_linhas`. `n = N` (`AmostragemIntegral`/
  `TabelaInteira`) zera a fpc → `SE=0` → sempre `ALTA`, sem `if` dedicado por
  estratégia. Amostra vazia → `BAIXA` direto (mesmo guard de
  `_metricas_vazias()`). Thresholds (ponto de partida, ajustáveis se os
  exemplos numéricos contra dado real pedirem recalibração):
  `ALTA ≤5pp / MEDIA (5,15]pp / BAIXA >15pp`.

- **Confiança é métrica de TABELA (`MetricaDeTabela`), não de coluna** —
  achado do usuário durante a revisão: como a fórmula usa `p=0,5` fixo, o
  nível depende só de `n`/`N`, idênticos para toda coluna da mesma tabela
  (a amostra é lida uma vez, por tabela). Calcular/exibir por coluna
  replicaria o mesmo valor N vezes. `MetricasDeConfianca(MetricaDeTabela)`
  com um único campo `nivel: NivelDeConfianca`, calculada em
  `AnalisadorDeMetricasDeTabela` (não em `AnalisadorDeMetricasDeColuna`,
  nem Analisador novo — `produz = [MetricasBaseTabela, MetricasDeConfianca]`,
  primeiro caso de um Analisador com 2 tipos no projeto). `tamanho_amostra`/
  `percentual_amostrado` não viram campo — já existem em
  `TabelaAnalisada.total_linhas`/`TabelaAnalisada.metadados_amostra.
  tamanho_amostra` (evita duplicar dado que pode divergir silenciosamente).
  Isso também resolve de graça a lacuna "confiança não cobre `completude`" —
  já nasce como métrica de tabela, lado a lado.

- **`GeradorDbt` só anota, nunca muda severidade de teste** — o registry-plan
  original (item 1 do escopo, texto "usado como critério adicional... para
  decidir severidade/supressão de sugestão") cogitava usar confiança para
  rebaixar/suprimir testes. O PO (arquiteto concordando) apontou que isso
  fere o NFR3 do PRD (mesma métrica sempre gera a mesma sugestão) e a
  idempotência entre reexecuções — decisão do usuário: nota em
  `schema.yml`/README, sem tocar `severity` de `unique`/`not_null`/
  `accepted_values`/etc.

- **`_LISTAR_TABELAS_SQL` precisa do filtro `relkind='p'` no pai**, não só
  `pg_inherits` puro — achado bloqueante do engenheiro de dados, validado
  contra Postgres 16 real: sem esse filtro, a exclusão também apaga tabelas
  de **herança clássica** (`CREATE TABLE filha () INHERITS (pai)`, ainda
  usada em bancos legados pré-PG10), que são tabelas reais e independentes,
  não fragmentos de uma partição — bug pior que o original (some com
  tabelas reais, em vez de duplicá-las).

- **Causa raiz do `total_linhas=0` da mãe corrigida:** não é "tabela
  particionada nunca tem storage" (falso desde PG14, `ANALYZE` manual na mãe
  já propaga `reltuples` agregado) — é que **autovacuum nunca roda `ANALYZE`
  automaticamente em `relkind='p'`**, só nas filhas físicas. A agregação a
  partir das filhas (que autovacuum sempre mantém atualizadas) continua
  sendo a correção certa, só a causa documentada muda.

- **Limitação "partição em schema diferente da mãe" removida** — testada
  empiricamente pelo engenheiro de dados (`loja_arquivo.pedidos_2023`
  particionando `loja.pedidos`), a query já exclui corretamente essa filha
  cross-schema (casa pela identidade da própria filha, não pelo schema do
  pai). Não é limitação real.

- **Limitação de sub-particionamento multi-nível reformulada:** não é só
  "não soma recursivamente" — um nó intermediário (`relkind='p'`) sofre o
  mesmo bug de "nunca autovacuumado automaticamente"; se a agregação de 1
  nível usar o valor bruto de um filho que é, ele mesmo, uma partição
  intermediária não analisada, o total da raiz herda um valor
  desatualizado **silenciosamente**, sem sinalizar erro. Aceito como fora
  de escopo v1, mas documentado com essa causa exata.

## Escopo desta issue

- [x] `NivelDeConfianca` (Enum) + `MetricasDeConfianca(MetricaDeTabela)` em
      `domain/model/analysis.py` — só `nivel`, calculado via fórmula de
      margem de erro com correção de população finita (ver acima)
- [x] `AnalisadorDeMetricasDeTabela` — `produz` ganha `MetricasDeConfianca`,
      calculada a partir de `tamanho_amostra`/`total_linhas` já disponíveis
- [x] `GeradorMarkdown`/`GeradorDbt`/`GeradorContextoDeIA` — consomem o sinal
      no nível tabela (nota "Confiança estatística" no Markdown, `meta.
      confianca_estatistica` em `schema.yml` + parágrafo no README do dbt
      sem mudar severidade de teste, campo `confianca` dentro de
      `metricas_tabela` no JSON, junto de `completude`/`amostra_vazia`).
      Helper `_metrica_de_confianca` extraído para `generators/comum/
      _metricas.py`, compartilhado pelos 3 (reuso real, mesma lógica de
      filtro repetida)
- [x] `extractors/postgres/_queries.py` — `_LISTAR_TABELAS_SQL` exclui
      partições filhas via `pg_inherits` + `relkind='p'` no pai; nova query
      `_FILHOS_DE_PARTICAO_SCHEMA_SQL`
- [x] `extractors/postgres/_construcao.py` — `montar_metadados_do_schema`
      agrega `total_linhas_por_tabela[mae] = sum(filhas)`
- [x] `mypy --strict`/`ruff` limpos — suíte completa (`src/` + `tests/`)

## Testes

- [x] Unit: `AnalisadorDeMetricasDeTabela` — amostra pequena/grande/vazia/
      `TabelaInteira`, fronteira dos thresholds, tabela com coluna PK (prova
      de que o nível não depende de proporção observada), invariância a
      `percentual_nulo` diferente por coluna (8 testes novos)
- [x] Unit: cada Gerador consumindo `MetricasDeConfianca` — Markdown (2),
      dbt (2, incluindo prova de que `severity` de teste soft não muda com
      `nivel=BAIXA`), ContextoDeIA (2) — feliz + métrica ausente não quebra
- [x] Unit: `montar_metadados_do_schema` com fixture mãe + 2 filhas — soma
      correta (`test_construcao.py`, feliz + borda de filha sem
      `total_linhas` conhecido)
- [x] Integração (testcontainers, Postgres real): tabela particionada com 2+
      partições reais — listagem mostra só a mãe, `total_linhas` bate com a
      soma real das partições, amostra vem da tabela-mãe normalmente; caso
      de herança clássica (`INHERITS`) convivendo no mesmo schema continua
      listada — decisão desta rodada: mudado de "Unit" (rascunho original)
      pra Integração, já que exige catálogo real (`pg_inherits`), não é
      testável sem Postgres. `test_extrator_postgres_particionamento.py`
      (3 testes) + schema `particionamento` novo em `conftest.py`
      compartilhado
- [x] Regressão: suíte de Extractors/Geradores segue verde — 654 unit +
      37 integração (Postgres) verdes; fixtures de
      `test_extrator_postgres.py` (mocks de `fetchall.side_effect`/
      `call_count`) e `test_listar_escopos_retorna_escopos_semeados`
      ajustados pro novo round-trip de 9 queries e pro schema novo

## Verificação final

- [x] `mypy --strict src` + `ruff check .` limpos
- [x] `pytest tests/unit` (667 testes) + `pytest tests/integration` (77
      testes, Postgres real com tabela particionada de verdade e MariaDB)
      verdes
- [x] Geração manual de artefato (Markdown/dbt/JSON) contra fixture com
      amostra pequena (n=4/N=1000, confiança baixa) e fixture lida por
      completo (n=N=5000, confiança alta) — nota "Confiança estatística"
      no Markdown, `meta.confianca_estatistica` em `schema.yml` (severity
      dos testes soft intacta), campo `confianca` no JSON, parágrafo
      explicativo no README, tudo conferido visualmente. Particionamento já
      coberto pelo teste de integração real (`test_extrator_postgres_
      particionamento.py`)

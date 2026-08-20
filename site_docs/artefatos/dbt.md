# Projeto dbt

O `GeradorDbt` escreve um projeto dbt standalone, camada staging, a partir do banco
analisado. Cada tabela vira um model que faz `CAST` explícito dos tipos de origem e
replica as colunas 1:1, sem nenhuma transformação de negócio. É o único artefato do `ddf`
em que os identificadores ficam em inglês: nomes de coluna, de model, e o vocabulário de
teste (`unique`, `not_null`, `relationships`, `accepted_values`) seguem o contrato real
que o dbt e o warehouse esperam, não uma escolha de estilo do restante do código.

## Estrutura gerada

```
.
├── dbt_project.yml
├── README.md
├── packages.yml            # só se algum teste depender de dbt_utils
├── macros/
│   ├── cast_type/           # só se algum tipo precisar de cast por adapter
│   ├── matches_format/      # só se alguma coluna tiver formato detectado
│   ├── unique_percentage_at_least.sql   # só com teste soft de unicidade
│   └── composite_relationships.sql      # só com FK composta no lote
└── models/
    └── staging/
        └── <escopo>/
            ├── sources.yml
            ├── stg_<escopo>__<tabela>.sql
            └── schema.yml
```

Cada escopo do lote analisado vira sua própria subpasta em `models/staging/`, autocontida
com `sources.yml`, um `.sql` por tabela e um `schema.yml` compartilhado. `packages.yml` e
os macros em `macros/` só são escritos quando há um teste real que dependa deles nesta
execução; se uma reextração deixa de precisar de um deles, o `ddf` remove o arquivo em vez
de deixá-lo órfão de uma execução anterior.

## Um model por tabela

O nome de cada model segue `stg_<escopo>__<tabela>`, prefixo necessário para evitar
colisão entre tabelas homônimas de escopos diferentes no mesmo grafo dbt. O SQL gerado é
sempre um `select` simples com `CAST` por coluna e a origem via `source()`, sem `join`,
filtro ou agregação, porque a camada de negócio fica por conta de quem consome esse
projeto dbt a partir daqui, não do `ddf`.

## Testes de qualidade a partir de métrica real

Cada coluna em `schema.yml` recebe uma lista de testes dbt, e a regra por trás de cada
sugestão é sempre a mesma métrica que a análise já calculou, nunca uma inferência sobre o
que a coluna "parece ser". É aqui que a arquitetura do `ddf` paga o que promete, porque
o mesmo cálculo estatístico que já é a base do domínio (ver
[Analisadores](../guia/analisadores.md)) também é o critério mecânico que decide qual
teste de qualidade entra no projeto dbt, sem uma segunda camada de heurística por cima.

- `unique`/`not_null` priorizam sempre o fato estrutural do schema (coluna com `UNIQUE`
  ou `NOT NULL` reais), com `severity: error`, o padrão do dbt. Na ausência de uma
  garantia estrutural, o `ddf` sugere o mesmo teste com `severity: warn` quando a métrica
  calculada sobre a amostra também aponta 100% de unicidade ou 0% de nulo, contanto que a
  amostra tenha um tamanho mínimo para sustentar a afirmação.
- `matches_format` é sugerido quando a coluna tem um formato detectado pela análise
  (e-mail, CPF, CNPJ, telefone ou CEP), sempre com `severity: warn`.
- Duas faixas soft cobrem o espaço entre "sem sinal" e o `unique`/`not_null` hard: uma
  coluna com uma proporção baixa, mas não nula, de valores nulos recebe
  `dbt_utils.not_null_proportion`; uma coluna quase toda única, mas não 100%, recebe
  `unique_percentage_at_least` (macro próprio do `ddf`). Os dois com `severity: warn`.
- `accepted_values` é sugerido quando a coluna atende aos critérios de elegibilidade para
  enumeração calculados pela análise, também com `severity: warn`.
- `relationships` é sugerido quando a coluna tem exatamente uma referência de FK própria
  e a tabela referenciada está no mesmo lote analisado. Uma coluna com FK composta não
  entra aqui, porque o teste equivalente, `composite_relationships`, vive no nível do
  model.
  Coluna com FK polimórfica (mais de uma referência sem discriminador) nunca recebe
  `relationships` automático, porque o teste assumiria que toda linha satisfaz uma única
  relação quando na prática pode satisfazer outra; o `ddf` emite um aviso em vez de
  arriscar um falso positivo garantido.

No nível do model, `dbt_utils.unique_combination_of_columns` é sugerido um por `UNIQUE`
composto real do schema, e `composite_relationships` um por FK composta cuja tabela
referenciada está no lote, ambos com `severity: error` porque refletem uma restrição
estrutural, não uma amostra.

## Confiança estatística como anotação

Cada model carrega `meta.confianca_estatistica` (`alta`, `media` ou `baixa`) em
`schema.yml`, calculada a partir do tamanho da amostra em relação ao total de linhas da
tabela. É só uma anotação informativa, e não muda a `severity` de nenhum teste sugerido.
Uma tabela com confiança `baixa` é um sinal para revisar manualmente os testes amostrais
dessa tabela antes de confiar neles, não um erro do `dbt test`.

## Avisos

O `ddf` agrupa os avisos deste gerador por categoria, em vez de emitir um por ocorrência:
quantas FKs compostas referenciam tabela fora do lote, quantas colunas têm FK polimórfica,
e quantas colunas têm FK fora do lote. Em qualquer um desses três casos o teste
correspondente é omitido, não gerado de forma incorreta.

## Como rodar

```bash
dbt deps   # só necessário se packages.yml foi gerado
dbt run
dbt test
```

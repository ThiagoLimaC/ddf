# Documentação Markdown

O `GeradorMarkdown` escreve um arquivo `.md` por tabela, mais um `index.md` de
navegação, a partir do banco analisado. Pensado para ser lido direto no repositório, sem
visualizador externo: qualquer pessoa com acesso ao GitHub consegue abrir uma tabela e
ver o que ela representa, sem rodar nada.

## Estrutura gerada

```
.
├── index.md
└── <escopo>/
    └── <tabela>.md
```

Cada tabela do lote analisado vira um arquivo na subpasta do seu escopo. `index.md` fica
na raiz do artefato e lista todas as tabelas, com link para cada uma.

## Índice

`index.md` traz uma tabela com todas as tabelas do lote, ordenadas por escopo e nome:

| Escopo | Tabela | Completude | Total de linhas |
|---|---|---|---|

O nome de cada tabela já é o link para o `.md` correspondente. Completude vem da mesma
métrica calculada na análise (ver [Analisadores](../guia/analisadores.md)).

## Página de uma tabela

Cada `.md` de tabela segue sempre a mesma sequência de seções.

O topo traz o papel de negócio e as regras de negócio registrados no override daquela
tabela (ver [Curadoria](../guia/curadoria.md)), ou "N/D" quando o override ainda não foi
preenchido.

### Fatos extraídos

Lista o escopo, o total de linhas, a completude, o tamanho da amostra analisada em
relação ao total, e o nível de confiança estatística da amostra. Quando a tabela tem
restrições `UNIQUE` compostas ou chaves estrangeiras compostas, elas também aparecem
aqui, com os grupos de coluna envolvidos.

### Colunas

Uma tabela com nome, tipo de dado (já formatado com precisão quando aplicável, ex.:
`NUMERIC(10,2)`, `VARCHAR(255)`), restrição e papel de negócio de cada coluna.

### Qualidade dos dados

Outra tabela, com percentual de nulo, percentual de único, mínimo, máximo e formato
detectado por coluna. Mínimo e máximo aparecem como "—" para categorias em que ordenar
não tem significado de negócio (texto, UUID, enum, booleano). Mostrar um valor ali seria
mais enganoso do que omitir, já que a ordenação nesses casos é lexicográfica, não a
esperada.

### Valores frequentes por coluna

Para cada coluna elegível, traz os valores mais observados na amostra com a contagem e o
percentual de cada um. Uma coluna que é chave primária ou tem restrição `UNIQUE` ainda
aparece aqui, mas com uma nota explicando que a lista tende a não ter sinal analítico,
porque os valores já tendem a ser únicos. Uma coluna 100% nula na amostra também aparece,
com uma nota dizendo isso em vez de uma lista vazia sem explicação.

## Restrições marcadas na coluna

A coluna "Restrição" da tabela de Colunas combina os marcadores que se aplicam:

- `PK` para chave primária.
- `FK → escopo.tabela.coluna` para cada referência de chave estrangeira da coluna. Uma
  coluna com mais de uma referência (FK polimórfica) mostra um marcador por referência.
- `FK (composta)` quando a coluna participa de uma chave estrangeira composta, além do
  marcador `FK → ...` de qualquer referência própria que ela também tenha.
- `UNIQUE` para restrição `UNIQUE` de coluna única, e `UNIQUE (composto)` quando a coluna
  participa de uma restrição `UNIQUE` composta.
- `NOT NULL` quando a coluna não aceita nulo no schema.

`UNIQUE`, `UNIQUE (composto)` e `NOT NULL` nunca aparecem numa coluna que já é `PK`: uma
chave primária já implica único e não nulo, marcar os dois seria redundante.

## Amostragem e geração

O rodapé de cada página de tabela registra a estratégia de amostragem usada, o percentual
e o seed quando aplicáveis, e quantas linhas foram de fato amostradas em relação ao total
da tabela. Quando a leitura não foi completa, um aviso lembra que as métricas de coluna
são estimativas sobre a amostra, não o dado inteiro. A data e hora de geração ficam
registradas em cada arquivo, incluindo o `index.md`.

## Avisos

Quando uma ou mais tabelas do lote não têm papel de negócio preenchido no override, o
`ddf` emite um único aviso ao final da geração, com a contagem de quantas tabelas estão
nessa situação, em vez de um aviso por tabela.

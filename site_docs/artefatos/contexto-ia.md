# Contexto para IA

O `GeradorContextoDeIA` escreve o banco analisado em JSON, dividido em um `index.json`
leve e um arquivo por tabela. Pensado para um agente de IA consumir sem abrir conexão com
o banco fonte: o contexto necessário para responder sobre o schema já está no artefato,
em vez de exigir uma consulta ao vivo.

## Por que dividido em vários arquivos

Um único JSON com o banco inteiro serializado obrigaria um agente a carregar tudo, mesmo
quando a tarefa só envolve uma ou duas tabelas. O `ddf` separa um `index.json` que só
lista as tabelas existentes e como elas se relacionam, do conteúdo detalhado de cada
tabela, que fica em um arquivo próprio. Um agente consegue então carregar só o
subconjunto do schema relevante à tarefa, prática conhecida como schema linking.

## Estrutura gerada

```
.
├── index.json
└── tabelas/
    └── <escopo>/
        └── <tabela>.json
```

Diferente do projeto dbt, aqui não há prefixo de escopo no nome do arquivo: a própria
subpasta `tabelas/<escopo>/` já desambigua uma tabela homônima entre escopos diferentes.

## `index.json`

O ponto de entrada do artefato. Traz o timestamp de geração, a lista de todas as tabelas
do lote com o caminho do arquivo de cada uma, e o grafo de relacionamentos entre elas.

O grafo é bidirecional: cada tabela lista as chaves estrangeiras que ela declara
(`referencia`) e as tabelas que apontam para ela (`referenciado_por`). `referencia` é
sempre completo, porque vem direto da chave estrangeira real da própria tabela, mesmo
quando a tabela referenciada não faz parte do lote analisado. `referenciado_por` só
enxerga o que está no lote: se ele for um recorte do banco, uma tabela de fora que também
referencia a tabela atual fica invisível ali. O `index.json` carrega uma nota fixa
avisando dessa limitação, em vez de tentar sinalizar caso a caso.

## Arquivo de uma tabela

Cada `tabelas/<escopo>/<tabela>.json` traz o conteúdo completo de uma tabela: nome,
escopo, papel de negócio e regras de negócio (vindos do override, ver
[Curadoria](../guia/curadoria.md)), total de linhas e os metadados da amostra usada.

Quando a análise já calculou as métricas da tabela, o JSON também traz completude e o
nível de confiança estatística da amostra, ao lado de uma flag indicando se a amostra
estava vazia. Sem essa flag, um agente não teria como distinguir "100% de completude
confirmada" de "nenhuma linha inspecionada", já que os dois casos produzem o mesmo número.

Restrições `UNIQUE` compostas e chaves estrangeiras compostas da tabela aparecem como
listas próprias, quando existirem. Cada coluna é serializada com seu tipo de dado, se é
chave primária ou estrangeira, suas referências, se aceita nulo, se é única, papel de
negócio, regras de negócio e as métricas calculadas pela análise (percentual de nulo,
percentual de único, valores frequentes, mínimo, máximo e formato detectado).

## Esquema de consulta

Quando pelo menos uma coluna da tabela sustenta um filtro de enumeração fechada, o JSON
inclui uma seção `esquema_de_consulta` com a lista dessas colunas: o nome, os valores
possíveis e a cobertura amostral daquela lista de valores sobre o total observado. É a
mesma pergunta que decide o teste `accepted_values` do projeto dbt (ver [Projeto
dbt](dbt.md)), aqui reaproveitada para sugerir a um agente que colunas fazem sentido como
filtro em uma consulta, em vez de texto livre.

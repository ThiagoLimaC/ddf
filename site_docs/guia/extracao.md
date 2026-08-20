# Extração

A extração é a etapa 1-5 do wizard: escolher a fonte, conectar, escolher escopos e
tabelas, escolher a estratégia de amostragem e ler. É a única etapa do `ddf` que abre
conexão com o banco. Tudo que vem depois (curadoria, análise, geração) trabalha sobre o
que foi extraído aqui, sem voltar à fonte.

## O que é lido

Para cada tabela escolhida, o `ddf` lê:

- Colunas e tipos de dado.
- Chaves primárias e chaves estrangeiras, simples ou compostas.
- Restrições `UNIQUE`, simples ou compostas.
- Uma amostra real dos dados, no tamanho e segundo a estratégia definidos em
  [Estratégias de amostragem](amostragem.md).

Nada disso é inferido. O `ddf` lê a estrutura direto do catálogo do banco; a amostra é o
único artefato que envolve leitura de dados propriamente dita, o resto é metadado de
schema.

## Os dois motores da v1

A conexão é feita por um adaptador nativo por fonte: `ExtratorPostgres` e
`ExtratorMariaDB`. Você escolhe qual dos dois usar logo na etapa 1 do wizard, mas os dois
seguem o mesmo contrato: a mesma estrutura sai extraída dos dois lados, e as etapas
seguintes (curadoria, análise, geração) se comportam de forma idêntica, qualquer que
tenha sido o motor escolhido. Novas fontes se conectam
por plugin, sem exigir mudança no `ddf`. Ver [Extensão via plugins](../extensao.md).

## Paralelismo

Tabelas são sempre extraídas em paralelo entre si. O wizard mostra uma barra de
progresso com o total de tabelas escolhidas.

Tabelas grandes o suficiente também podem ser lidas em paralelo internamente, dividindo
a própria tabela em partes lidas ao mesmo tempo. Isso é decidido automaticamente por
tabela, sem pergunta no wizard. Quando as condições não se aplicam (tabela pequena,
particionada, ou a leitura paralela falha por algum motivo), o `ddf` cai para o caminho
sequencial normal, sem interromper a extração.

## Conexão e reconexão

Antes de extrair qualquer tabela, o `ddf` testa a conexão com a fonte. Se a conexão
falhar, o wizard pergunta se você quer tentar de novo, até 3 tentativas. Cada nova
tentativa pede os dados de conexão outra vez, para o caso de o problema ser uma
credencial ou parâmetro digitado errado, não a rede.

## Avisos

- **Falha ao extrair uma tabela específica** não interrompe o lote: as demais tabelas
  seguem sendo extraídas normalmente, e a falha aparece como aviso ao final.
- **Amostra maior que o total de linhas estimado da tabela** é um indício de que a
  estimativa de catálogo está desatualizada (a fonte não passou por uma coleta de
  estatísticas recente), não um erro do `ddf`.
- **FK composta sem chave correspondente no lado referenciado** aparece quando uma
  chave estrangeira composta aponta para colunas que não formam uma chave primária nem
  uma restrição `UNIQUE` conhecida na tabela referenciada, ou quando essa tabela está
  fora do lote extraído nesta execução e por isso não dá para verificar. É sintoma de
  schema legado em que a integridade referencial não está garantida pelo próprio banco.

## Próximo passo

Com as tabelas extraídas, o `ddf` aplica a curadoria existente e gera os skeletons de
override que faltam. Ver [Curadoria (overrides)](curadoria.md). A estratégia de
amostragem escolhida nesta etapa também é o que baliza o nível de confiança calculado
depois, em [Analisadores (métricas)](analisadores.md).

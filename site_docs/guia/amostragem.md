# Estratégias de amostragem

A estratégia de amostragem é escolhida uma vez por execução, na etapa 3 do wizard, logo
depois de conectar e antes de extrair. Ela decide como cada tabela é lida: quantas
linhas entram na amostra e por qual mecanismo elas são selecionadas.

## Por que a estratégia importa

A amostra escolhida aqui é o que sustenta o restante do pipeline: as métricas
calculadas em [Analisadores](analisadores.md), os testes de qualidade sugeridos no
projeto dbt e as restrições marcadas na documentação Markdown. Cada estratégia toca
cobertura, custo de leitura e reprodutibilidade de forma diferente, e a escolha certa
depende do tamanho das tabelas e do que se espera da análise depois.

## Percentual de linhas

Amostra um percentual das linhas de cada tabela, escolhido linha a linha por um
mecanismo probabilístico nativo do banco (`TABLESAMPLE BERNOULLI` no Postgres, `WHERE
RAND() <= p` no MariaDB).

O custo real dessa estratégia não escala com o tamanho da amostra: tanto o Postgres
quanto o MariaDB fazem uma varredura sequencial completa da tabela antes de decidir
quais linhas entram, então um percentual pequeno em uma tabela de dezenas de milhões de
linhas ainda lê a tabela inteira, só descarta a maior parte depois de ler. Em bancos com
tabelas muito grandes, isso pode tornar a extração mais lenta do que o percentual
escolhido sugere. O wizard avisa desse custo assim que você escolhe essa estratégia.

Um seed opcional torna a amostra reprodutível entre execuções; sem seed, cada execução
amostra linhas diferentes.

## Tabela inteira

Lê a tabela completa, sem nenhum mecanismo de amostragem. É a opção certa quando a
tabela é pequena o suficiente para caber em memória e você quer a cobertura máxima
possível, sem viés estatístico de nenhum tipo.

Como não há percentual para limitar o volume lido, essa estratégia carrega a tabela
inteira em memória de uma vez, o que pode esgotar a memória disponível em tabelas muito
grandes. Por isso o wizard pede confirmação explícita antes de seguir com essa escolha.

## Amostragem por faixa

Amostra um percentual das linhas, mas lidas por faixas contíguas em vez de linha a
linha: blocos físicos de dados no Postgres, faixas de chave primária no MariaDB. O custo
de leitura escala com o percentual pedido, não com o total de linhas da tabela, o que a
torna mais barata que "Percentual de linhas" em tabelas grandes.

Em troca, essa estratégia é sujeita a viés de cluster: linhas de uma mesma faixa
contígua tendem a se parecer entre si, por exemplo por terem sido inseridas na mesma
janela de tempo. Isso pode distorcer métricas como percentual de nulos, percentual de
valores únicos e valores mais frequentes em tabelas alimentadas em lote ou particionadas
por tempo. Por ser opt-in, o `ddf` nunca troca para essa estratégia sozinho, e o wizard
avisa desse viés assim que você a escolhe.

Como em "Percentual de linhas", um seed opcional torna a escolha das faixas
reprodutível entre execuções.

## Reflexo na análise

O tamanho real da amostra lida aqui, comparado ao total de linhas estimado da tabela, é
o que decide o nível de confiança estatística calculado depois, em
[Analisadores (métricas)](analisadores.md). Uma amostra que cobre a tabela inteira
("Tabela inteira", ou "Percentual de linhas"/"Amostragem por faixa" com percentual
próximo de 100) tende a produzir confiança alta; uma amostra pequena em uma tabela
grande tende a produzir confiança mais baixa, mesmo que os dados amostrados sejam
representativos.

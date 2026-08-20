# Estratégia de amostragem

[Estratégias de amostragem](../guia/amostragem.md) cobre o assunto do ponto de vista de
quem roda o wizard: quando escolher cada uma, e o trade-off de custo ou viés envolvido.
Esta página cobre a Porta em si, como cada Extrator traduz a mesma política em SQL real, e
por que essa tradução diverge tanto entre Postgres e MariaDB.

## O Port não sabe gerar SQL

`EstrategiaDeAmostragem` (`domain/ports/estrategia_de_amostragem.py`) expõe só duas
propriedades: `nome`, o identificador gravado em `MetadadosDeAmostra.estrategia`, e
`requisicao`, um `RequisicaoDeAmostragem` (`AmostragemProbabilistica`, `AmostragemIntegral`
ou `RequisicaoPorFaixa`) que descreve **quanto** amostrar. Nenhum método da Porta produz
SQL, `TABLESAMPLE`, `WHERE` ou qualquer outro mecanismo concreto. A própria docstring da
Porta explica o motivo dado o fato que traduzir a política em consulta concreta cabe a cada Extrator, já
acoplado ao dialeto da própria fonte, para não amarrar a política de amostragem a nenhum
banco específico. Custo de execução também é responsabilidade de cada Extrator, não da
Porta: a Porta descreve só "quanto", nunca "quão caro" é fazer isso num motor específico.

## Seed: reprodutibilidade fixa, não aleatoriedade reprodutível

`seed_efetivo` (`extractors/comum/seed_efetivo.py`) é o único ponto que decide qual seed
cada Extrator usa de fato, e os dois motores passam por ele antes de montar a query, tanto
para `AmostragemProbabilistica` quanto para `RequisicaoPorFaixa`. Quando o usuário não
informa um seed, a função não sorteia um valor novo por execução, ele devolve uma constante
fixa (`1`) sendo a mesma para qualquer tabela, em qualquer execução, em qualquer motor.

Sem seed explícito, o `ddf` sempre
lê a mesma fatia da tabela. A consequência é dupla. A favor, isso dá diff estável em Git
entre execuções sucessivas visto que passa a ser a mesma amostra, as mesmas linhas, sem o artefato mudar por ruído de
amostragem que não reflete nenhuma mudança real na fonte. Contra, se essa fatia fixa calhar
de não ser representativa da tabela, o viés nunca é percebido, porque a amostra nunca varia
entre execuções para expor a diferença. Rotacionar a amostra fica por conta do usuário,
passando um seed explícito diferente a cada vez que quiser uma fatia nova.

O seed realmente usado, explícito ou o default, é gravado em `MetadadosDeAmostra.seed` e
não só consumido na query e descartado. Uma amostra antiga sempre pode ser reproduzida a
partir do artefato gerado, mesmo que ninguém lembre se um seed foi passado na hora.

## Três políticas, três tipos de requisição

| Estratégia | `requisicao` | O que descreve |
|---|---|---|
| `PercentualDeLinhas` | `AmostragemProbabilistica(percentual, seed)` | Uma fração das linhas, decidida por um mecanismo probabilístico do próprio motor. |
| `TabelaInteira` | `AmostragemIntegral()` | Leitura completa, sem mecanismo de amostragem. |
| `AmostragemPorFaixa` | `RequisicaoPorFaixa(percentual, seed)` | Uma fração das linhas, lida por faixas contíguas em vez de linha a linha. |

`TabelaInteira` não é só `PercentualDeLinhas(percentual=100)` com outro nome: o resultado
prático das duas é equivalente, mas cada Extrator monta um `SELECT *` puro para
`AmostragemIntegral`, sem passar pelo mecanismo probabilístico do motor. Isso deixa a
intenção "quero a tabela inteira" explícita em `metadados_amostra.estrategia`, em vez de
depender de quem lê o artefato saber que percentual=100 produz o mesmo resultado.

## Postgres: um mecanismo nativo por caso

`montar_consulta_amostra` (`extractors/postgres/_construcao.py`) monta uma única query por
tipo de `requisicao`, todas variações do mesmo `SELECT * FROM schema.tabela ...`:

- `AmostragemProbabilistica` vira `TABLESAMPLE BERNOULLI (percentual) REPEATABLE (seed)`:
  o Postgres avalia uma moeda com viés por linha varrida, o que exige varrer a tabela
  inteira antes de decidir quais linhas entram, independente do `percentual` pedido.
- `AmostragemIntegral` vira um `SELECT *` sem cláusula de amostragem.
- `RequisicaoPorFaixa` vira `TABLESAMPLE SYSTEM (percentual) REPEATABLE (seed)`: o Postgres
  sorteia blocos de 8KB inteiros em vez de linhas individuais, então blocos fora do sorteio
  nunca são lidos. É esse mecanismo que faz o custo de `AmostragemPorFaixa` escalar com o
  `percentual` pedido, não com o total de linhas da tabela, e é também a origem do viés de
  cluster: linhas do mesmo bloco físico tendem a ter sido escritas na mesma janela de
  tempo.

Os dois mecanismos existem prontos no Postgres, funcionam sobre qualquer tabela, e não
dependem da forma da chave primária. `seed_efetivo` preenche um valor determinístico
quando o usuário não informa um, e esse valor é devolvido para `extrair_tabela` gravar o
seed realmente usado nos metadados da amostra, não só na query executada.

## MariaDB: sem `TABLESAMPLE`, aproximação construída no Extrator

O MariaDB não tem equivalente a `TABLESAMPLE`. `ExtratorMariaDB.extrair_tabela` monta a
query de amostra na própria etapa de leitura, com um mecanismo diferente por caso:

- `AmostragemProbabilistica` vira `WHERE RAND(seed) <= percentual / 100`: mesma
  característica de custo do `BERNOULLI` do Postgres, uma varredura completa que avalia a
  condição linha a linha, independente do `percentual` pedido.
- `AmostragemIntegral` vira um `SELECT *` sem cláusula de amostragem.
- `RequisicaoPorFaixa` não tem mecanismo nativo nenhum para reaproveitar. O `ddf` constrói
  uma aproximação a partir do domínio da chave primária:
    - **Elegibilidade**: `_elegibilidade_de_pk_para_faixa` só aceita PK de coluna única e
      tipo inteiro (`tinyint`/`smallint`/`mediumint`/`int`/`bigint`), os únicos tipos onde
      `MAX(pk)` e um corte `pk >= valor` fazem sentido aritmético. PK composta, ausente ou
      de outro tipo (`UUID`, `VARCHAR`, `DATE`...) não serve. Nesse caso, a leitura cai para
      o mesmo `WHERE RAND(seed) <= percentual / 100` de `AmostragemProbabilistica`, com um
      `Aviso` nomeando o motivo do fallback.
    - **Quando elegível**: `_k_faixas_para` decide quantas faixas sortear (mínimo 10,
      crescendo até 50 conforme o total de linhas passa de 1 milhão), para aproximar o
      espalhamento de blocos do `TABLESAMPLE SYSTEM` do Postgres sem uma consulta por linha
      amostrada. Uma única `SELECT MAX(pk) FROM tabela` estabelece o teto do domínio, e os
      `k` cortes são sorteados no lado do Python (`random.Random(seed)`), não via `RAND()`
      dentro do `WHERE`: `RAND(seed)` no MariaDB é reavaliado a cada linha varrida pelo
      motor, o que faria o corte derivar sistematicamente para o início do intervalo de PK,
      em vez de sortear um ponto fixo. A consulta final é um `UNION ALL` de `k`
      subconsultas, cada uma `WHERE pk >= corte ORDER BY pk LIMIT linhas_por_faixa`.
    - Quando a amostra retornada vem com menos da metade das linhas pedidas, o `ddf` emite
      um `Aviso` apontando gaps densos na chave primária logo após os pontos sorteados como
      causa provável.

## Onde isso cruza com paralelismo intra-tabela

A leitura paralela intra-tabela também particiona por faixa (`ctid` no Postgres, faixa de
PK no MariaDB), mas resolve um problema diferente: dividir a leitura de uma tabela grande
entre várias conexões, não decidir quanto amostrar. Hoje ela reaproveita a mesma checagem
de elegibilidade de PK do MariaDB descrita acima, mas é restrita a `AmostragemIntegral` (a
combinação de faixas de amostragem com faixas de paralelismo não é suportada nesta
versão). O mecanismo de particionamento em si, os números de paralelismo medidos e a
ausência de `pg_export_snapshot` no MariaDB estão detalhados em
[Pipeline e paralelismo](pipeline-e-paralelismo.md).

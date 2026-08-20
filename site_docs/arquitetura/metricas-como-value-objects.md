# Métricas como Value Objects

Esta é a decisão que mais sustenta a leitura do `ddf` como cruzamento real entre
arquitetura de backend e ciência de dados. A mesma disciplina de modelagem que evita
estado mutável descontrolado num sistema de backend é o que confina o efeito de uma
métrica nova a um único lugar do código.

## Por que Value Object, não campo

`MetricaDeColuna` e `MetricaDeTabela` são Value Objects: imutáveis (`model_config =
ConfigDict(frozen=True)`), sem identidade própria, definidos inteiramente pelos valores
que carregam. Toda métrica concreta (percentual de nulo, valores mais frequentes, nível de
confiança estatística) herda de uma das duas.

A alternativa óbvia seria adicionar cada métrica nova como campo em `ColunaAnalisada` ou
`TabelaAnalisada`. É a alternativa proibida no `ddf`, porque um campo novo nesses modelos
exige mudar o modelo, o que exige revisar todo Gerador que já lê `ColunaAnalisada`/
`TabelaAnalisada`, mesmo os que não têm nada a ver com a métrica nova. Uma métrica nova
como Value Object é um arquivo novo herdando de `MetricaDeColuna` ou `MetricaDeTabela`, sem
mudança em nenhum modelo existente.

Isso não dispensa trabalho: um Gerador que quer efetivamente exibir a métrica nova precisa
do próprio código pra filtrá-la (por `isinstance`) e renderizá-la. O que muda é o raio da mudança dado que um Gerador que ignora a métrica nova não precisa ser tocado, revisado, nem sequer saber que ela existe,
porque ele nunca lia este campo específico.

```python
# correto: arquivo novo, zero mudanças em código existente
class MetricasDeDistribuicao(MetricaDeColuna):
    origem: str = "AnalisadorDeDistribuicao"
    assimetria: float
    curtose: float
    histograma: list[tuple[float, float]]
```

`ColunaAnalisada`/`TabelaAnalisada` carregam uma lista de métricas
(`metricas: list[MetricaDeColuna]` / `list[MetricaDeTabela]`), e cada Gerador filtra por
`isinstance` o subconjunto que sabe interpretar. Adicionar uma métrica que nenhum Gerador
existente conhece ainda não quebra nenhum deles: eles simplesmente não a encontram na
filtragem, e continuam produzindo exatamente o que produziam antes.

## As métricas calculadas hoje

Três Value Objects concretos existem na v1, produzidos pelos dois Analisadores nativos:

| Value Object | Escopo | Produzido por | Campos |
|---|---|---|---|
| `MetricasBaseColuna` | `ColunaAnalisada` | `AnalisadorDeMetricasDeColuna` | `percentual_nulo`, `percentual_unico`, `valores_frequentes` (até 10), `minimo`, `maximo`, `formato_detectado` |
| `MetricasBaseTabela` | `TabelaAnalisada` | `AnalisadorDeMetricasDeTabela` | `completude` |
| `MetricasDeConfianca` | `TabelaAnalisada` | `AnalisadorDeMetricasDeTabela` | `nivel` (`ALTA`/`MEDIA`/`BAIXA`) |

O significado de cada campo do ponto de vista de quem lê o artefato gerado está em
[Analisadores](../guia/analisadores.md); aqui a tabela mostra só a forma do dado.
`MetricasDeConfianca` é métrica de tabela mesmo dependendo apenas de
`tamanho_amostra`/`total_linhas` — que já existem em `TabelaAnalisada`/
`MetadadosDeAmostra` — para não duplicar por coluna um valor que é idêntico para todas as
colunas da mesma tabela.

## `produz`/`requer`: dependência declarada, validada antes de rodar

Analisadores podem depender de métricas calculadas por outro Analisador (a completude de
uma tabela, por exemplo, depende das métricas de nulo já calculadas por coluna). Geradores
dependem de métricas específicas para funcionar (o `GeradorDbt` não tem o que sugerir sem
`MetricasBaseColuna`). Em vez de descobrir essa dependência em runtime, com um Gerador
tentando ler uma métrica que nunca foi calculada, todo Analisador e Gerador declara
`produz` e `requer` explicitamente:

```python
class MeuAnalisador:
    produz: list[type] = [MinhaMetrica]
    requer: list[type] = [MetricasBaseColuna]
```

A CLI valida essas dependências antes de executar qualquer coisa. Uma combinação inválida
(por exemplo, `GeradorMarkdown` sem `AnalisadorDeMetricasDeTabela` selecionado) falha com
uma mensagem nomeando a métrica ausente, antes de qualquer extração começar, nunca a meio
de uma execução longa.

## Prova concreta: um critério, dois Geradores

O exemplo mais direto de que essa arquitetura paga o que promete é
`_elegivel_para_enumeracao` (`generators/comum/_metricas.py`), a função que decide se uma
coluna sustenta um teste `accepted_values` no projeto dbt ou uma sugestão de enum no
contexto de IA. Cinco critérios, todos obrigatórios:

1. Categoria de dado fora de `TIMESTAMP`, `DATE`, `TIME`, `UUID`, `JSON`, `ARRAY`:
   categorias temporais são monotônicas por natureza (nenhuma amostra torna um "criado em"
   um universo fechado); `UUID` é identidade, nunca categoria; `JSON`/`ARRAY` são
   incompatíveis com enumeração fechada.
2. Amostra da tabela com pelo menos 100 linhas, mesmo piso já usado pelo Analisador para
   evitar que uma amostra pequena pareça 100% categórica por coincidência de tamanho.
3. Contagem real de valores distintos menor que 10, reconstruída a partir de
   `percentual_unico` sobre o tamanho da amostra, não o tamanho da lista truncada de
   `valores_frequentes` (que só guarda os top-10; sem essa reconstrução, uma coluna com
   200 valores distintos concentrados nos 10 mais comuns passaria como se fosse
   exaustiva).
4. `percentual_unico` da coluna abaixo de 10%, como sinal adicional de baixa cardinalidade
   relativa.
5. Cobertura dos top-10 valores mais frequentes sobre os valores não nulos da amostra
   maior ou igual a 90%.

`GeradorDbt` chama essa função para decidir se sugere `accepted_values` em `schema.yml`
(ver [Projeto dbt](../artefatos/dbt.md)); `GeradorContextoDeIA` chama a mesma função para
decidir se marca uma coluna como enumerável no contexto de IA. Nenhum dos dois reimplementa
o critério à sua própria maneira, porque os dois leem a mesma métrica, calculada uma única
vez, e aplicam a mesma regra mecânica sobre ela. É o resultado direto de a métrica ser
Value Object compartilhável, e não campo duplicado por Gerador. A mesma peça de análise
estatística que faz parte do domínio também é o critério de decisão dos artefatos, sem uma
segunda camada de heurística por Gerador.

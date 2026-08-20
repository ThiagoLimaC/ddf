# Analisadores (métricas)

A análise roda logo depois da curadoria, entre a etapa de artefatos e a confirmação
final do wizard. Diferente das etapas anteriores, não há decisão do usuário aqui, porque o
`ddf` calcula as métricas automaticamente, sobre os dados já curados.

## Quando rodam

Toda análise roda de forma incondicional, sobre a amostra de cada tabela curada. Não há
menu de seleção. Ao contrário de Extratores e Geradores, que o wizard pergunta quais
usar, todo Analisador registrado no `ddf` executa em toda extração. As métricas
resultantes alimentam tanto a documentação Markdown quanto os testes sugeridos no
projeto dbt, então rodar sempre garante que os dois artefatos reflitam o mesmo cálculo.

## Métricas de coluna

Por coluna, o `ddf` calcula:

- Percentual de nulos.
- Percentual de valores únicos, entre os valores não nulos.
- Os valores mais frequentes, com a contagem de cada um.
- Valor mínimo e valor máximo observados na amostra.
- Formato detectado, só para colunas de texto: e-mail, CPF, CNPJ, telefone ou CEP,
  quando a maioria dos valores da coluna segue um desses padrões. CPF, CNPJ, telefone e
  CEP seguem o formato brasileiro, não um padrão internacional genérico. Colunas
  numéricas, de data ou de outros tipos não passam por essa detecção.

Todas essas métricas são calculadas sobre a amostra extraída, não sobre a tabela
inteira na fonte, exceto quando a estratégia de amostragem escolhida já lê a tabela por
completo.

## Métricas de tabela

Por tabela, o `ddf` calcula:

- Completude, a média do quanto cada coluna está preenchida (o inverso do percentual de
  nulos), agregada em um único número por tabela.
- Nível de confiança estatística da amostra, classificado como ALTA, MÉDIA ou BAIXA. O
  cálculo compara o tamanho da amostra lida com o total de linhas estimado da tabela: uma
  amostra que cobre a tabela inteira sempre produz confiança ALTA; amostras parciais são
  classificadas pela margem de erro estatística que esse tamanho de amostra implica.

## Onde essas métricas aparecem

As métricas calculadas aqui, não inferência, são a base dos testes de qualidade
sugeridos no `schema.yml` do projeto dbt e das restrições marcadas na documentação
Markdown. Ver [Artefatos gerados](../artefatos/index.md) para o formato completo de cada
artefato.

## Avisos

Quando uma tabela tem uma amostra pequena demais para que suas métricas sejam
estatisticamente confiáveis, o `ddf` emite um único aviso agregado ao final da análise,
em vez de um aviso por tabela ou por coluna. Esse aviso resume quantas tabelas e quantas
colunas foram afetadas, sobre o total analisado, para sinalizar que aquelas métricas
específicas merecem menos confiança sem sobrecarregar a saída do wizard em extrações com
muitas tabelas pequenas.

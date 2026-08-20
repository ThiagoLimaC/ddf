# Artefatos gerados — visão geral

Um artefato aqui é qualquer resultado que o `ddf` escreve em disco a partir da mesma
extração e análise. Nenhum dos três volta ao banco fonte, nem recalcula métrica própria.
A diferença entre eles é só o consumidor final.

## Um levantamento, três saídas

O wizard extrai a estrutura e uma amostra dos dados uma única vez, aplica a curadoria dos
overrides e calcula as métricas de análise uma única vez. Cada gerador escolhido na etapa
6 do wizard (ver [Guia rápido](../guia-rapido.md)) lê esse mesmo resultado e escreve na
sua própria subpasta, sem depender dos outros geradores nem recalcular nada por conta
própria.

| Artefato | Formato | Para quem |
|---|---|---|
| [Projeto dbt](dbt.md) | `dbt_project.yml`, `sources.yml`, um model por tabela e `schema.yml`, prontos para `dbt run`/`dbt test`. | Quem roda o pipeline de dados a partir daqui. |
| [Documentação Markdown](markdown.md) | Um `.md` por tabela mais um `index.md` de navegação. | Quem lê a documentação direto no GitHub, sem visualizador externo. |
| [Contexto para IA](contexto-ia.md) | Um `index.json` mais um `.json` por tabela. | Um agente de IA, que carrega só o subconjunto do schema relevante à tarefa. |

## O que os três têm em comum

Papel de negócio e regras de negócio registrados nos overrides (ver
[Curadoria](../guia/curadoria.md)) aparecem nos três artefatos, cada um no formato que faz
sentido para o seu consumidor. O mesmo vale para as métricas: percentual de nulo,
percentual de único, valores frequentes, mínimo, máximo, formato detectado e confiança
estatística (ver [Analisadores](../guia/analisadores.md)) vêm da mesma análise nos três,
sem reinterpretação por gerador. Os três também agrupam tabelas pela mesma estrutura de
escopo usada na extração, cada um com sua própria convenção de subpasta, e nenhum depende
de um visualizador especial. Todos passam por revisão de código normal antes de qualquer
uso.

## Próximos passos

- [Projeto dbt](dbt.md): estrutura completa, e a regra por trás de cada teste de
  qualidade sugerido.
- [Documentação Markdown](markdown.md): o que aparece em cada seção de uma página de
  tabela.
- [Contexto para IA](contexto-ia.md): estrutura do `index.json` e do chunk por tabela.

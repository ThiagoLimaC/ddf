# Tecnologias

A stack do `ddf` não foi escolhida item a item por preferência. Cada peça central resolve
um problema específico do pipeline, e várias decisões só fazem sentido em conjunto. Esta
página cobre o porquê de cada uma, com mais profundidade nas que carregam uma decisão de
arquitetura real por trás, e mais direto nas que são só infraestrutura de suporte.

## Polars

`pl.DataFrame` existe só dentro de `TabelaExtraida`, `TabelaCurada`, `BancoCurado` e
`ContextoDeAnalise`, e nenhum Gerador importa Polars (ver
[Métricas como Value Objects](metricas-como-value-objects.md)). Isso já é meio caminho do
porquê da escolha. O resto é o que Polars faz bem dentro dessa fronteira, em quatro
frentes concretas.

A primeira é paralelismo interno via Rayon. Os Analisadores rodam fora do pool de threads
do `OrquestradorParalelo` de propósito: o cálculo de métrica sobre um `pl.DataFrame` já
paraleliza internamente via Rayon, a biblioteca de paralelismo de dados do Rust por trás do
Polars, sem precisar de nenhuma orquestração adicional em Python.

A segunda é a API lazy. Polars permite construir um plano de operações (`select`/`filter`/
`cast`) e só materializar o resultado quando necessário, em vez do modelo eager do pandas,
que executa cada operação imediatamente. Essa diferença de modelo de execução foi um dos
motivos reais da escolha, independente do ganho de paralelismo.

A terceira é interoperabilidade nativa com Arrow, sem cópia extra a partir do
`connectorx`. `connectorx` decodifica direto do driver do banco para o formato Arrow
(`cx.read_sql(..., return_type="polars")`), a peça que sustenta o paralelismo intra-tabela
fora do GIL (ver [Pipeline e paralelismo](pipeline-e-paralelismo.md)). Polars é
Arrow-native: os dados chegam do `connectorx` sem uma camada de conversão intermediária.
Pandas é baseado em NumPy, então o mesmo caminho exigiria uma conversão Arrow → NumPy no
meio. Usar Polars aqui não é só preferência de biblioteca, é a peça que aproveita, sem
custo de conversão, uma dependência que o `ddf` já tem por outro motivo.

A quarta é schema e tipagem mais estritos, coerentes com o resto do projeto. Pandas tem um
index implícito, um dtype `object` que aceita tipos mistos sem avisar, e um histórico de
ambiguidade entre cópia e view de um DataFrame (`SettingWithCopyWarning`). Polars tem
schema explícito e dtypes mais estritos. Não foi o motivo original da escolha, mas combina
com a disciplina de tipagem do resto do `ddf`, onde os quatro tipos do pipeline são
estruturalmente distintos sob `mypy --strict` (ver
[Testes e qualidade](testes-e-qualidade.md)). Polars encaixa aqui porque o resto do projeto
já é rigoroso com tipo, não só por causa de performance.

## connectorx

Biblioteca Rust que decodifica resultado de query direto para Arrow/Polars, liberando o
GIL do Python durante a decodificação (`py.allow_threads`). O histórico completo, incluindo os números de benchmark que
motivaram a troca, está em
[Pipeline e paralelismo](pipeline-e-paralelismo.md#paralelismo-intra-tabela-uma-decisao-movida-por-medicao-nao-por-intuicao).

## Pydantic

Todo modelo de domínio do `ddf` é Pydantic. Isso garante validação de dado, imutabilidade
onde faz sentido (`frozen=True` nas métricas, Value Objects por definição) e serialização
consistente. `arbitrary_types_allowed=True` é restrito às quatro classes que carregam
`pl.DataFrame` (`TabelaExtraida`, `TabelaCurada`, `BancoCurado`, `ContextoDeAnalise`).
Nenhum outro modelo usa essa configuração, incluindo `BancoAnalisado`, que é Pydantic puro.
A mesma serialização Pydantic (`model_dump_json`) é o que o `GeradorContextoDeIA` usa como
base para produzir o contexto em JSON consumido por agentes de IA.

## Jinja2

Templates Jinja são o mecanismo central de dois dos três Geradores do `ddf`. `GeradorMarkdown` usa `tabela.md.jinja2` e `index.md.jinja2`, com um
conjunto de filtros Jinja próprios (`generators/markdown/_filtros.py`) que formatam tipo de
dado com precisão (`NUMERIC(10,2)`), combinam marcadores de restrição (`PK`, `FK → ...`,
`UNIQUE`) e escapam célula de tabela Markdown. A lógica de formatação vive nos filtros
Python; o template só decide onde cada valor já formatado entra.

`GeradorDbt` vai além de dois templates (`stg_tabela.sql.jinja2`, `readme.md.jinja2`): os
macros de teste customizado (`matches_format`, `cast_type`) usam as próprias tags Jinja do
dbt-core (`{% test %}`, `{% macro %}`), lidas como texto puro pelo `ddf`. O `Environment`
Jinja do próprio `ddf` não conhece essas tags; só o dbt-core em runtime as interpreta.
Esses macros seguem o padrão `adapter.dispatch` do dbt: uma implementação por motor
(`postgres__cast_type.sql`, `mariadb__cast_type.sql`), despachada em runtime pelo adapter
dbt configurado no projeto gerado. É o mesmo padrão citado em
[Extensão via plugins](../extensao.md) como o custo real de dar suporte pleno a um motor de
banco novo no `GeradorDbt`: não basta implementar o `Extrator`, é preciso também um
conjunto de templates Jinja por motor.

O ambiente Jinja do `ddf` é configurado com `trim_blocks`/`lstrip_blocks`/
`keep_trailing_newline` (controle fino de espaço em branco, necessário porque a saída é
SQL/Markdown versionado, sensível a linha em branco espúria) e `autoescape=False`, porque a
saída não é HTML e escapar automaticamente produziria SQL ou Markdown corrompido.

## O resto da stack

- `psycopg2-binary`/`pymysql`: driver nativo de cada motor, um por Extrator concreto,
  mesma separação de responsabilidade do resto do Extraction Context.
- `dbutils`: `PooledDB`, pool de conexões reaproveitado pelos dois Extratores.
- `pyarrow`: formato de troca entre `connectorx` e Polars, e dependência interna do
  próprio Polars para operações que envolvem Arrow.
- `click`: framework de CLI que estrutura o comando `ddf`.
- `questionary`: prompts interativos do wizard (múltipla escolha, confirmação).
- `colorama`: cor no terminal com suporte cross-platform, incluindo Windows.
- `pyyaml`: leitura e escrita dos overrides de curadoria.
- `dbt-core`/`dbt-postgres` (grupo `dev`): valida que o projeto dbt gerado roda de
  verdade contra um Postgres real, não só que o YAML tem a forma esperada. O lado
  MariaDB passa pela mesma validação, mas fora do grupo `dev`: `dbt-mysql` (único
  adapter dbt com suporte a `type: mariadb`) trava em `dbt-core<=1.7`, incompatível com
  Python 3.12 e com `mypy>=2.1.0` do próprio projeto. O teste de integração provisiona,
  sob demanda, um venv Python 3.11 isolado com `dbt-core==1.7.19`+`dbt-mysql`, cacheado
  entre execuções e nunca instalado no venv principal.
- `mypy`, `ruff`, `pytest`, `testcontainers` (grupo `dev`): guard-rails de CI, detalhados
  em [Testes e qualidade](testes-e-qualidade.md).

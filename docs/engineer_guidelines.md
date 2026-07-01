# Engineering Guidelines — ddf (novo)

Este documento define padrões e boas práticas de engenharia para quem contribuir
com código neste projeto.


## Extensão via `Protocol`, nunca via classe orquestradora com `if`s

- Toda nova fonte de dados, heurística de análise ou formato de saída entra
  implementando o `Protocol` correspondente em `dominio/portas/`
  (`Extractor`, `Analyzer`, `Generator`) e se conectando ao pipeline como mais
  um item na lista passada para `compose(...)`.
- **Proibido reintroduzir uma classe `UseCase`** que encapsule múltiplos `Stage`s
  com `if`s internos decidindo o que rodar — é exatamente o padrão que esta
  arquitetura existe para evitar.
- "Pular uma etapa" (ex.: já ter o `DatabaseAnalisado` pronto de uma execução
  anterior) nunca é um parâmetro opcional dentro de uma classe que serve os dois
  casos — é simplesmente não incluir aquele estágio na composição daquela
  chamada.
- Um `Stage` que não implementa o `Protocol` correspondente não compila contra
  `compose(...)` — a conformidade com o contrato é verificada por `mypy
  --strict`, não por convenção documentada.

## Tipagem como garantia, não como documentação

- `DatabaseExtraido`, `DatabaseCurado` e `DatabaseAnalisado` são tipos Pydantic
  diferentes — `mypy --strict` rejeita, em tempo de verificação, qualquer
  composição que tente pular uma etapa do pipeline.
- Rode `mypy --strict` localmente antes de cada commit — não confie só no CI
  para pegar um erro de tipo; o ciclo de feedback é mais rápido rodando antes de
  empurrar a mudança.

## Nomenclatura: idioma como contrato, não como preferência

- **Identificadores internos** (funções privadas, variáveis locais, parâmetros,
  módulos internos, nomes de teste) — **português**.
- **Contratos externos** — classes de domínio, campos Pydantic, `Protocol`s, e
  qualquer chave que vaze para um arquivo de saída (JSON de contexto de IA, YAML
  de overrides, `schema.yml` do dbt) — **inglês**.

## Docstrings: resumo de uma linha, Google style

```python
def is_failure(self) -> bool:
    """Verifica se a operação falhou."""
```

Descrição objetiva do método e parâmetros.

## Guard-rails de lint e CI

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "D"]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

CI roda lint + `mypy --strict` + `pytest` a cada push, desde o primeiro PR
mergeado — nunca como uma issue de limpeza posterior. Nenhum PR é mergeado com o
pipeline vermelho.

---

# Política de testes

## Cobertura mínima obrigatória, por categoria deliberada

Todo `Stage` (Extractor, Analyzer, Overrides, Generator, ou função de
composição) e todo `Adapter` novo precisa de, no mínimo, estas três categorias:

1. **Caminho feliz** — comportamento esperado com entrada válida e
   representativa.
2. **Erro esperado** — uma falha de domínio real (conexão recusada, schema
   ausente, arquivo malformado) retornando `Result.failure`, nunca uma exceção
   solta.
3. **Borda** — um caso limite real do domínio que o `Stage` precisa tratar
   (tabela vazia, coluna sem dados na amostra, valor com caractere especial, FK
   que referencia algo fora da extração atual).

**O que NÃO conta como teste de borda:** um caso que só existe por acidente de
tipagem do Python e que `mypy --strict` já rejeita em tempo de verificação.

O número de cenários por categoria não é fixo — pode (e deve) ser mais de um
"caso de borda" por `Stage`, se o domínio tiver mais de um caso limite real. O
que importa não é bater a lista de 3 itens, é a lista de testes ser
**deliberada**.

## A pergunta que decide se um teste entra na suíte

Antes de escrever um teste, pergunte: **"que bug real ou regra de negócio este
teste pegaria, que não seria pego de outra forma (tipo, lint, teste já
existente)?"** Se a resposta for "nenhum", o teste não vai para a suíte.

Essa pergunta separa dois tipos de teste:

- **Teste-armadilha real** (o que queremos): nasce de um bug concreto já
  encontrado ou de uma regra de negócio que, se quebrada, o teste pega.
  Docstring honesto sobre a causa
  (`"""Bug: coluna timestamp com top_values não deve gerar accepted_values
  absurdo."""`), e a assertion realmente verifica o comportamento que o
  docstring promete.
- **Teste decorativo** (o que queremos evitar): passa por acidente de
  comportamento do Python/framework, não por uma validação intencional do
  código — ou o docstring promete mais do que a assertion verifica (ex.:
  "interrompe a execução" sem nunca checar que a etapa seguinte de fato não
  rodou).

## Testabilidade por isolamento — sem montar o pipeline inteiro

Como cada `Stage` é uma função/classe testável isoladamente (recebe um tipo de
entrada conhecido, devolve um `Result` de um tipo de saída conhecido), o teste de
um Analyzer novo não exige montar o pipeline inteiro nem mockar os estágios
vizinhos — só chamar o `Stage` direto com a entrada que seu tipo declara.

```
tests/
├── unit/
│   ├── pipeline/                  # compose() e a semântica de parar no 1º erro
│   ├── dominio/modelo/            # validação dos modelos Pydantic
│   └── infraestrutura/adaptadores/
│       ├── extratores/             # conftest.py desde o primeiro teste
│       ├── analisadores/
│       └── geradores/
└── integration/
    ├── extratores/                 # bancos/arquivos/API reais (ou containers)
    └── api/                         # endpoints da camada de serving (futuro)
```

## `conftest.py` desde o primeiro teste de cada camada

Ao escrever o primeiro teste de uma camada (`extratores`, `analisadores`,
`geradores`), já criar o `conftest.py` correspondente com os mocks/builders
óbvios.

## Testes de CLI mockam o `Protocol`, nunca o driver de baixo nível

A camada de CLI sempre recebe/constrói um Extractor (ou Analyzer/Generator)
através de uma forma testável (registro de fontes, injeção explícita) — testes
de CLI mockam o `Protocol` correspondente (ou diretamente o `Stage`), nunca o
driver de baixo nível de uma implementação concreta (ex.: `psycopg2.connect`).

## Validação de Open/Closed como teste, não só como princípio citado

Sempre que uma `Port` (Extractor, Analyzer, Generator) ganha uma nova
implementação real, existe pelo menos um teste que prova que adicioná-la não
exigiu editar nenhuma implementação já existente.


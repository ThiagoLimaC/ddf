# Tarefas 


## 1. Setup do ambiente de desenvolvimento

- [ ] `uv init`, `pyproject.toml` com Python 3.12+ e as dependências base
      (pydantic, driver do Postgres, jinja2, pyyaml, click, questionary)
- [ ] Estrutura de pastas: 
        `src/ddf/domain/{model,ports,shared}`,
        `src/ddf/pipeline/`, 
        `src/ddf/infrastructure/adapters/{extractors,analyzers,generators,cli}`, 
        `tests/unit/...`, 
        `tests/integration/...`
- [ ] `ruff` com `select = ["E","F","W","I","N","D"]` e
      `pydocstyle convention = "google"`
- [ ] `mypy --strict`
- [ ] Workflow de CI (GitHub Actions) rodando `ruff` + `mypy` + `pytest` a cada
      push

## 2. Modelo de domínio utilizando Pydantic

- [ ] `Aviso` (dataclass) em `domain/shared/` — `mensagem: str`, `origem: str` (nome do Stage que produziu o aviso)
- [ ] `Result[T]` como **sum type** em `domain/shared/`
       ```python
       @dataclass(frozen=True)
       class Sucesso(Generic[T]):
            value: T
            warnings: list[Aviso] = field(default_factory=list)

        @dataclass(frozen=True)
        class Falha:
            error: str

        Result = Sucesso[T] | Falha
        ```
- [ ] `DataType` rico em `domain/model/` — categoria + `precision`/`scale`/
      `max_length` opcionais
- [ ] `Column` (Pydantic) — nome, `data_type: DataType`, métricas opcionais
      (`null_percent`, `unique_percent`, `top_values`, `min`, `max`,
      `detected_format`, `is_primary_key`, `is_foreign_key`,
      `referenced_table`, `referenced_column`), e `business_role`/
      `business_rules` (presentes desde aqui — ver item abaixo)
- [ ] `Table` (Pydantic) — nome, schema, colunas, `row_count`, `completeness`,
      `business_role`/`business_rules`
- [ ] **`business_role`/`business_rules` em `Table`/`Column` desde o início** —
      porque o mecanismo de overrides (tópico 4) aplica sobre o
      `DatabaseExtraido`, antes do `DatabaseAnalisado` existir
- [ ] `DatabaseExtraido` e `DatabaseAnalisado` como tipos Pydantic **distintos**
      — não a mesma classe reaproveitada em dois estados
- [ ] `Stage[Entrada, Saida]` (`Protocol` genérico) em `pipeline/estagio.py`:
      ```python
      class Stage(Protocol[Entrada, Saida]):
          def __call__(self, entrada: Entrada) -> Result[Saida]: ...
      ```
- [ ] `compose(*stages)` em `pipeline/compor.py` — desembrulha `.value` de cada
      `Result` antes do próximo estágio, **acumula `warnings`** de todos os
      estágios bem-sucedidos, para no primeiro `Result.failure`:
      ```python
      def compose(*stages: Stage) -> Stage:
          def pipeline(entrada):
              valor = entrada
              avisos: list[str] = []
              for estagio in stages:
                  resultado = estagio(valor)
                  if resultado.is_failure():
                      return resultado
                  avisos += resultado.warnings
                  valor = resultado.value
              return Result.success(valor, warnings=avisos)
          return pipeline
      ```
- [ ] `Extractor` e `Generator` (`Protocol`s vazios) em `domain/ports/`
- [ ] **Verificação:** teste de validação Pydantic (campo obrigatório, range
      0-100 de `null_percent`/`unique_percent`); teste de `compose()` cobrindo
      2+ estágios fake com sucesso, parada no 1º `Result.failure`, acúmulo de
      warnings de 2+ estágios bem-sucedidos, e garantia de tipo (`mypy --strict`
      rejeita um `Stage[DatabaseAnalisado, ...]` recebendo `DatabaseExtraido`)
- [ ] **Decisão a confirmar antes de implementar:** onde vivem as funções
      adaptadoras (`extrair_de`, `analisar_com`, `gerar_com`,
      `aplicar_overrides_de`) que embrulham um Extractor/Analyzer/Generator
      concreto na forma de `Stage` — ainda não fechado neste plano

## 3. Adapter de extractor concreto

- [ ] `PostgresExtractor`: parsing de connection string, conexão via driver,
      leitura de `information_schema` (tabelas, colunas — incluindo
      `numeric_precision`/`numeric_scale`/`character_maximum_length` —, PK, FK)
- [ ] Popular o `DataType` rico a partir do `information_schema`, não só o
      nome do tipo
- [ ] Amostragem representativa (`ORDER BY random()` ou `TABLESAMPLE`)
- [ ] `conftest.py` de `tests/unit/infrastructure/adapters/extratores/`
      nasce com o primeiro teste desta camada
- [ ] Script de desenvolvimento descartável ou teste de integração em
      `tests/integration/extratores/` contra um Postgres real/containerizado
- [ ] **Verificação:** caminho feliz (tabela com FK, tipo numérico com
      precisão/escala), erro esperado (connection string malformada, conexão
      recusada), borda real (tabela vazia, tabela sem colunas)

## 4. Mecanismo de overrides com leitura, merge e idempotência

- [ ] Leitura de YAML em `overrides/<schema>/<tabela>.yaml`
- [ ] Hash de estrutura a partir de campos estruturais do `DatabaseExtraido`
      (nome, tipo, PK/FK) — nunca de métrica calculada
- [ ] Escrita/atualização de skeleton sem sobrescrever curadoria já existente
- [ ] `aplicar_overrides_de(overrides_dict)` como
      `Stage[DatabaseExtraido, DatabaseExtraido]`
- [ ] **Verificação:** idempotência (reexecutar sobre a mesma estrutura não
      altera curadoria já editada); coluna nova recebe campo vazio sem tocar
      nos existentes; coluna removida gera warning sem apagar o override órfão

## 5. Analyzer que calcula métricas do database extraído já curado

- [ ] `ColumnMetricsAnalyzer`: `null_percent`, `unique_percent`, `min`/`max`,
      `top_values`, detecção de formato (email/cpf/cnpj/phone/cep)
- [ ] `TableMetricsAnalyzer`: `completeness` agregada a partir das colunas
- [ ] **Preservar** `business_role`/`business_rules` já aplicados pelo
      mecanismo de overrides (tópico 4) — não recalcular do zero e descartar
- [ ] `conftest.py` de `tests/unit/infrastructure/adapters/analisadores/`
      nasce com o primeiro teste desta camada
- [ ] **Verificação:** tipo numérico com precisão, tabela com FK, tabela
      vazia, coluna com formato detectável; teste de Open/Closed (Analyzer novo
      plugado na composição sem editar os já existentes); teste com um
      Extractor **fake** de segunda fonte (comprova a decisão fechada: não
      existe Analyzer por Extractor)

## 6. Adapter de generator concreto

- [ ] **Antes de qualquer generator real:** decidir a forma do `Generator`
      Stage (`Stage[DatabaseAnalisado, DatabaseAnalisado]`) e a camada de
      seleção da CLI, usando `Stage`s fake — incluindo o teste de regressão
      "múltiplos generators + um produz warning, sem mascarar o resultado dos
      anteriores"
- [ ] `MarkdownGenerator` — documentação humana
- [ ] `DbtGenerator` — `dbt_project.yml` + `sources.yml` + `stg_*.sql` (cast
      usando o `DataType` rico) + `schema.yml` com testes sugeridos
      deterministicamente (unique, not_null, relationships, accepted_values
      com verificação de cobertura de domínio, formato por regex)
- [ ] `AiContextGenerator` — thin, só reformata o que o Analyzer já calculou
- [ ] **Verificação:** critério de saída de cada generator (ver
      `plano_desenvolvimento.md`); `dbt run`/`dbt test` do projeto gerado
      executa de fato contra um banco de teste ou container

## 7. CLI real wizard

- [ ] Registro de fontes selecionáveis (extensível — não fixo em Postgres)
- [ ] Fluxo: escolher fonte → conectar (com retry) → extrair → aplicar
      overrides → analisar → escolher generators → confirmar → executar
- [ ] Testes de CLI injetam um `Extractor` fake pela costura de injeção do
      registro de fontes — nunca mockam o driver de baixo nível direto
- [ ] **Decisão já tomada:** não existe modo `--manual`/scriptável paralelo ao
      wizard
- [ ] **Verificação:** fluxo completo ponta a ponta com generators
      selecionados, falha de conexão com retry, nenhum generator selecionado
      retorna erro claro

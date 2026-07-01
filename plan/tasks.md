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
      `business_rules` 
- [ ] `Table` (Pydantic) — nome, schema, colunas, `row_count`, `completeness`,
      `business_role`/`business_rules`
- [ ] **`business_role`/`business_rules` em `Table`/`Column` desde o início** —
      porque o mecanismo de overrides (tópico 4) aplica sobre o
      `DatabaseExtraido`, antes do `DatabaseCurado`/`DatabaseAnalisado` existirem
- [ ] `DatabaseExtraido`, `DatabaseCurado` e `DatabaseAnalisado` como tipos
      Pydantic **distintos** (três, não dois) — não a mesma classe reaproveitada
      em estados implícitos; `DatabaseCurado` é a saída do estágio de overrides
      e a entrada do Analyzer, tornando estruturalmente impossível pular a
      curadoria, do mesmo jeito que a separação `DatabaseCurado`/
      `DatabaseAnalisado` torna impossível pular a análise
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
- [ ] `Extractor`, `Analyzer` e `Generator` (`Protocol`s vazios) em
      `domain/ports/` — as três `Port`s do sistema, cada uma plugável de forma
      independente 
- [ ] **Verificação:** teste de validação Pydantic (campo obrigatório, range
      0-100 de `null_percent`/`unique_percent`);

## 3. Adapter de extractor concreto

- [ ] `PostgresExtractor`: parsing de connection string, conexão via driver,
      leitura de `information_schema` 
- [ ] Popular o `DataType` rico a partir do `information_schema`
- [ ] Amostragem representativa 
- [ ] `conftest.py` de `tests/unit/infrastructure/adapters/extratores/`
- [ ] Script de desenvolvimento descartável ou teste de integração em
      `tests/integration/extratores/` contra um Postgres real/containerizado

## 4. Mecanismo de overrides com leitura, merge e idempotência

- [ ] Leitura de YAML em `overrides/<schema>/<tabela>.yaml`
- [ ] Hash de estrutura a partir de campos estruturais do `DatabaseExtraido`
      (nome, tipo, PK/FK) — nunca de métrica calculada
- [ ] Gerar skeleton YAML para usuário preencher o `business_rule` e o `business_rules`
      de cada table e column
- [ ] O arquivo deve de ser lido na mesma execução, e a ida à próxima etapa se dá
      pela confirmação do usuário que esses campos foram preenchidos
- [ ] Escrita/atualização de skeleton sem sobrescrever curadoria já existente

## 5. Analyzer que calcula métricas do `DatabaseCurado`

- [ ] O Analyzer recebe um result ontendo um objeto do tipo `DatabaseExtraido` 
      do Extractor
- [ ] `ColumnMetricsAnalyzer`: `null_percent`, `unique_percent`, `min`/`max`,
      `top_values`, detecção de formato (email/cpf/cnpj/phone/cep)
- [ ] `TableMetricsAnalyzer`: `completeness` agregada a partir das colunas
- [ ] **Preservar** `business_role`/`business_rules` já aplicados pelo
      mecanismo de overrides

## 6. Adapter de generator concreto

- [ ] `MarkdownGenerator` — documentação humana
- [ ] `DbtGenerator` — `dbt_project.yml` + `sources.yml` + `stg_*.sql` (cast
      usando o `DataType` rico) + `schema.yml` com testes sugeridos
      deterministicamente (unique, not_null, relationships, accepted_values)
- [ ] `AiContextGenerator` — thin, só reformata o que o Analyzer já calculou

## 7. CLI real wizard

- [ ] Registro de fontes selecionáveis (extensível — não fixo em Postgres)
- [ ] Fluxo: escolher fonte → conectar (com retry) → extrair → aplicar
      overrides → analisar → escolher generators → confirmar → executar
- [ ] Testes de CLI injetam um `Extractor` fake pela costura de injeção do
      registro de fontes — nunca mockam o driver de baixo nível direto

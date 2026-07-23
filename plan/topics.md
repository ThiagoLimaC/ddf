# Tópicos a serem implementados

- **Setup do ambiente de desenvolvimento**
  - `uv`, `pyproject.toml`, estrutura de pastas
  - Dependências base: pydantic, psycopg2-binary, polars, jinja2, pyyaml,
    click, questionary
  - CI (GitHub Actions) rodando `ruff` + `mypy --strict` + `pytest` a cada push

- **Modelo de domínio**
  - Shared: `Aviso`, `Resultado[T]` (Sucesso | Falha)
  - Common: `TipoDeDado`, `MetadadosDeAmostra`, `ConfiguracaoDeExtracao`
  - Extraction Context: `ColunaExtraida`, `TabelaExtraida`
  - Curation Context: `ColunaCurada`, `TabelaCurada`, `BancoCurado`
  - Analysis Context (Value Objects): `MetricaDeColuna`, `MetricasBaseColuna`,
    `MetricaDeTabela`, `ColunaAnalisada`, `TabelaAnalisada`,
    `BancoAnalisado`, `ContextoDeAnalise`, `iniciar_contexto()`
  - Pipeline: `Estagio[Entrada, Saida]`, `compor(*estagios)`
  - Ports: `Extrator`, `Analisador` (com `produz`/`requer`),
    `Gerador` (com `requer`), `OrquestradorDeTabelas`, `EstrategiaDeAmostragem`

- **Adaptador de Extrator concreto**
  - `PercentualDeLinhas` (EstrategiaDeAmostragem padrão — política pura de
    percentual, sem SQL; escala entre tabelas de tamanhos diferentes;
    substitui a `LimiteAleatorio` original de LIMIT absoluto)
  - `ExtratorPostgres` — `information_schema`, `ThreadedConnectionPool`
    preguiçoso, mapeamento de tipos (incluindo `FLOAT`/`CHAR`/`UUID`/`TIME`
    novos em `TipoDeDado`), amostragem via `TABLESAMPLE BERNOULLI` (sem viés
    posicional), `total_linhas` via `pg_class.reltuples`
  - Teste de integração via `testcontainers` contra Postgres 16 real
  - `conftest.py` de `tests/unit/infrastructure/adapters/extractors/`
  - Teste de integração via `testcontainers` em `tests/integration/extractors/`

- **Sobrescrita (ACL Extraction → Curation) e OrquestradorParalelo**
  - `SobrescritaDeTabela` — hash estrutural, skeleton YAML, idempotência,
    `Estagio[TabelaExtraida, TabelaCurada]` puro e thread-safe
  - `OrquestradorParalelo` — `ThreadPoolExecutor`, acumulação de erros,
    agregação `list[TabelaCurada]` → `BancoCurado`

- **Analisadores**
  - `AnalisadorDeMetricasDeColuna` — métricas por coluna via Polars,
    `produz=[MetricasBaseColuna]`
  - `AnalisadorDeMetricasDeTabela` — `completude`, `produz=[MetricasBaseTabela]`,
    `requer=[MetricasBaseColuna]`

- **Geradores concretos**
  - `GeradorMarkdown` — `requer=[MetricasBaseColuna, MetricasBaseTabela]`
  - `GeradorDbt` — `requer=[MetricasBaseColuna]`, testes determinísticos, cast SQL,
    única saída em inglês (contrato do dbt)
  - `GeradorContextoDeIA` — `requer=[MetricasBaseColuna]`, JSON compacto

- **CLI real wizard**
  - `EXTRATORES_REGISTRADOS` + `registrar_extrator()`
  - `validar_dependencias(analisadores, geradores)` — valida `produz`/`requer`
  - Fluxo completo com pausa para curadoria
  - `Aviso`s em streaming por etapa concluída
  - Código de saída `0`/`1`

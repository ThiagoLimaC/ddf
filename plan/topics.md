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
  - Analysis Context (Value Objects): `MetricaDeColuna`, `MetricasBase`,
    `MetricaDeTabela`, `ColunaAnalisada`, `TabelaAnalisada`,
    `BancoAnalisado`, `ContextoDeAnalise`, `iniciar_contexto()`
  - Pipeline: `Estagio[Entrada, Saida]`, `compor(*estagios)`
  - Ports: `Extrator`, `Analisador` (com `produz`/`requer`),
    `Gerador` (com `requer`), `OrquestradorDeTabelas`, `EstrategiaDeAmostragem`

- **Adaptador de Extrator concreto**
  - `LimiteAleatorio` (EstrategiaDeAmostragem padrão)
  - `ExtratorPostgres` — `information_schema`, `ThreadedConnectionPool`,
    mapeamento de tipos, amostragem via `EstrategiaDeAmostragem`
  - `conftest.py` de `tests/unit/infrastructure/adapters/extractors/`

- **Sobrescrita (ACL Extraction → Curation) e OrquestradorParalelo**
  - `SobrescritaDeTabela` — hash estrutural, skeleton YAML, idempotência,
    `Estagio[TabelaExtraida, TabelaCurada]` puro e thread-safe
  - `OrquestradorParalelo` — `ThreadPoolExecutor`, acumulação de erros,
    agregação `list[TabelaCurada]` → `BancoCurado`

- **Analisadores**
  - `AnalisadorDeMetricasDeColuna` — métricas por coluna via Polars,
    `produz=[MetricasBase]`
  - `AnalisadorDeMetricasDeTabela` — `completude`, `produz=[MetricasDeTabela]`,
    `requer=[MetricasBase]`

- **Geradores concretos**
  - `GeradorMarkdown` — `requer=[MetricasBase, MetricasDeTabela]`
  - `GeradorDbt` — `requer=[MetricasBase]`, testes determinísticos, cast SQL,
    única saída em inglês (contrato do dbt)
  - `GeradorContextoDeIA` — `requer=[MetricasBase]`, JSON compacto

- **CLI real wizard**
  - `FONTES_REGISTRADAS` + `registrar_fonte()`
  - `validar_dependencias(analisadores, geradores)` — valida `produz`/`requer`
  - Fluxo completo com pausa para curadoria
  - `Aviso`s em streaming por etapa concluída
  - Código de saída `0`/`1`

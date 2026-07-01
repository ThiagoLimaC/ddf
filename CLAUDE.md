# CLAUDE.md — ddf

## Antes de qualquer desenvolvimento

Leia os documentos abaixo nesta ordem. Não inicie nenhuma implementação sem
ter consultado os arquivos relevantes para a issue em questão.

| Documento | O que contém |
|---|---|
| [`plan/global.md`](plan/global.md) | Ordem das fases e dependências entre tasks |
| [`docs/system_design_doc.md`](docs/system_design_doc.md) | Arquitetura, fluxo de dados, decisões de design |
| [`docs/low_level_design.md`](docs/low_level_design.md) | Assinaturas, tipos e comportamento esperado de cada componente |
| [`plan/tasks.md`](plan/tasks.md) | Checklist detalhado da task em execução |
| [`docs/engineer_guidelines.md`](docs/engineer_guidelines.md) | Convenções de código, testes e regras de arquitetura |
| [`docs/gitflow.md`](docs/gitflow.md) | Branches, commits, padrão de PR e critérios de merge |

---

## Regras inegociáveis

**Bounded Contexts:** nunca importe tipos do Analysis Context em Extraction ou
Curation, e vice-versa. As únicas pontes são `SobrescritaDeTabela` (ACL
Extraction → Curation) e os Analisadores (ACL Curation → Analysis).

**Métricas como Value Objects:** nova métrica = novo tipo herdando de
`MetricaDeColuna` ou `MetricaDeTabela`. Proibido adicionar campos de métrica
diretamente em `ColunaAnalisada` ou `TabelaAnalisada`.

**Polars:** `pl.DataFrame` existe apenas em `TabelaExtraida`, `TabelaCurada`,
`BancoCurado` e `ContextoDeAnalise`. Nenhum Gerador importa `polars`.

**`produz`/`requer`:** todo Analisador e Gerador declara explicitamente quais
métricas produz e requer. A CLI valida antes de executar.

**`arbitrary_types_allowed=True`:** apenas nos quatro modelos que carregam
`pl.DataFrame`. Nenhum outro modelo usa essa configuração.

**Nomenclatura:** identificadores internos em português; contratos externos
(campos Pydantic, Protocols, chaves de artefatos) em inglês.

**`mypy --strict` + `ruff` antes de todo commit.** CI não passa com pipeline
vermelho.

---

## Convenções de teste

Três categorias obrigatórias por Stage/Adapter: caminho feliz, erro esperado
e borda. Testes de CLI injetam `Extrator` fake via `FONTES_REGISTRADAS` — nunca
mockam o driver de baixo nível. Consulte [`docs/engineer_guidelines.md`](docs/engineer_guidelines.md)
para a política completa.

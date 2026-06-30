## Tópicos a serem implementados

- Setup do ambiente de desenvolvimento
    - uv, pyproject.toml, estrutura de pastas
    - CI (GitHub Actions) rodando lint + mypy + pytest a cada push

- Modelo de domínio utilizando Pydantic
    - Column, Table, Database
    - Datype
    - Campos de curadoria (business_role, business_rule) em Table/Column
    - Result[T] como sum type: Sucesso[T] / Falha
    - Aviso (mensagem + origem)
    - Stage[Entrada, Saida] e compose(*stages)

- Adapter de extractor concreto
    - PostgresExtractor
    - confest.py

- Mecanismo de overrides com leitura, merge e idempotência
    - Leitura/escrita de YAML em `overrides/<schema>/<table>.yaml
    - Hash de estrutura

- Analyzer que calcula métricas do database extraído já curado
    - ColumnMetricsAnalyzer/TableMetricsAnalyzer/DatabaseMetricsAnalyzer

- Adapter de generator concreto
    - Adapter MarkdownGenerator
    - Adapter DbtGenerator
    - Adapter AiContextGenerator

- CLI real wizard
    - Executa as funções exibindo resultados
        - Escolher fonte
        - conectar
        - extrair 
        - aplicar overrides
        - analisar
        - escolher generators
        - confirmar
        - executar
        - Warnings exibidos em streaming, por etapa concluída


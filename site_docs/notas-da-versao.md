# Notas da versão

## v1: lançamento inicial

A partir de uma única extração, o `ddf` gera três artefatos versionáveis (projeto dbt,
documentação Markdown e contexto para IA), com curadoria humana preservada entre
reexecuções.

- Extração: dois motores nativos, Postgres e MariaDB, cada um lendo estrutura, chaves,
  restrições e uma amostra real de cada tabela em paralelo. Três estratégias de
  amostragem: percentual de linhas, tabela inteira e amostragem por faixa.
- Curadoria: papel de negócio e regras de negócio registrados em overrides YAML,
  preservados entre reextrações da mesma fonte. Mudança estrutural real é detectada e
  avisada, sem apagar curadoria de colunas que continuam existindo.
- Análise: duas frentes de métrica, por coluna e por tabela, calculadas automaticamente
  sobre os dados curados, sem decisão do usuário.
- Artefatos: três Geradores, um projeto dbt rodável com testes de qualidade sugeridos a
  partir de métrica real, documentação Markdown navegável, e contexto denso em JSON para
  agente de IA.
- Extensão: `Extrator` e `Gerador` são pontos de extensão reais desde esta versão,
  descobertos via `importlib.metadata.entry_points`, com o mesmo mecanismo usado pelos
  Adapters nativos.

!!! note "Fora do escopo desta versão"
    - Fontes além de Postgres e MariaDB (arquivo, API) ficam para avaliação futura, sem
      prioridade definida.
    - O `ddf` é uma ferramenta de análise sob demanda que produz artefatos versionáveis,
      não um MCP server: não mantém conexão contínua com a fonte nem expõe um serviço
      consultável em tempo real.
    - Sugestão de teste de qualidade é limitada a regras determinísticas sobre métrica
      real; não há detecção estatística de anomalia nem inferência baseada em modelo.
    - O `ddf` é consumido só pela linha de comando nesta fase, sem camada de consulta via
      API ou web.
    - Sem heurísticas de análise automática avançadas, como inferir relacionamento por
      convenção de nome de coluna ou gerar glossário de domínio automaticamente.
    - Testes de integração contra banco real cobrem hoje Postgres e MariaDB, via
      `testcontainers`; a mesma prática acompanha a chegada de cada fonte nova, não é
      antecipada.

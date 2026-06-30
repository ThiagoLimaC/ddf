# PRD — ddf (novo)

## Problem Statement

Bancos relacionais acumulam estrutura — tabelas, colunas, relacionamentos — sem
documentação atualizada. Entender essa estrutura do zero (pra integrar com ela ou
auditá-la) é trabalho manual, repetitivo, e que envelhece rápido.

## Visão / Solução

A partir de uma única extração de uma fonte de dados, gerar múltiplos artefatos
versionáveis e curados por humanos:

1. **Projeto dbt standalone e rodável** (o pitch) — `dbt_project.yml` +
   `sources.yml` + modelos de staging + `schema.yml` já populado com testes de
   qualidade sugeridos deterministicamente a partir das métricas extraídas.
2. **Documentação Markdown** — legível por humano, navegável, versionável.
3. **Contexto denso em JSON** — pensado para um agente de IA consumir o schema
   sem precisar de acesso ao banco.
4. **Curadoria humana via overrides** — papel de negócio e regras de
   tabelas/colunas, editáveis em YAML, preservados entre reexecuções.

Não é uma ferramenta de conexão ao vivo (não é um MCP server) — é uma ferramenta
de análise batch que produz artefatos revisáveis em PR.

## Para quem é

Projeto de interseção entre backend e dados, que demonstra competência em boas
práticas de engenharia de software aplicadas a um produto voltado para dados —
desde a extração até a geração de artefatos versionáveis.

## Regras de negócio

- Toda extração produz artefatos versionáveis e revisáveis em PR; nada é
  aplicado automaticamente fora do controle de versão.
- Curadoria humana (overrides) nunca é sobrescrita sem necessidade — idempotência
  decidida por hash de estrutura da fonte, não por timestamp ou execução.
- Sugestão de teste de qualidade é puramente determinística (mapeamento
  métrica → teste); nunca estatística ou baseada em modelo opaco — o "porquê" de
  cada teste sugerido precisa ser rastreável.
- Aprovação do que foi gerado é a própria revisão do PR; não existe etapa ou
  arquivo de aprovação separado.
- Erro esperado (conexão recusada, schema ausente, arquivo malformado) nunca
  propaga como exceção solta entre camadas — sempre reportado de forma explícita,
  com mensagem clara.
- Trocar a fonte de dados (Extractor) ou adicionar um novo artefato (Generator)
  nunca exige modificar um componente já existente — só compor uma lista
  diferente.

## Requisitos funcionais

1. Como usuário, quero conectar a uma fonte de dados via connection string e
   extrair schema + métricas reais de uma vez, para documentar a fonte sem
   inspeção manual.
2. Quero receber um projeto dbt standalone e rodável, com testes de qualidade já
   sugeridos a partir das métricas reais, para não escrever sources/staging/
   testes manualmente a cada fonte nova.
3. Quero documentação Markdown legível e navegável gerada da mesma extração, sem
   custo adicional de trabalho manual.
4. Quero um contexto denso em JSON, pensado para um agente de IA consumir o
   schema sem acessar o banco diretamente.
5. Quero curar manualmente o papel de negócio e as regras de tabelas/colunas via
   arquivo editável, e que essa curadoria sobreviva a reextrações da mesma fonte.
6. Quero escolher, a cada execução, qual fonte extrair e quais artefatos gerar,
   sem que essa escolha exija mudança em código já existente.
7. Quero que falhas esperadas sejam reportadas com mensagem clara e código de
   saída diferente de zero, nunca como stack trace de exceção solta.

## Fora de escopo

- Fontes de dados além de Postgres (MariaDB, API, arquivo) — pós-fundação, sem
  ordem de prioridade definida ainda.
- Heurísticas de análise novas (inferência de FK por convenção de nome,
  glossário de domínio automático) — candidatas a um projeto-estudo separado.
- Sugestão de teste de qualidade estatística/por anomalia, além do mapeamento
  determinístico.
- Camada de serving HTTP (API) — porta mencionada na arquitetura, sem roadmap
  definido.
- Testes de integração contra banco real, além de um smoke test pontual do
  Extractor.

## Critério de sucesso

1. **Funcional:** conecta a um Postgres real, extrai um banco de exemplo, e o
   `dbt run`/`dbt test` do projeto gerado executa de fato sobre esse banco, com
   testes sugeridos que fazem sentido numa revisão manual do diff. Documentação
   Markdown e contexto de IA saem de brinde da mesma extração.
2. **Arquitetural:** trocar o Extractor ou adicionar um Generator não exige
   tocar em nenhum componente já existente — só montar uma composição diferente.
3. CI verde (lint + type-check estrito + testes) desde o primeiro PR mergeado.
a
## Further notes

- Nome de marketing/exibição do projeto continua em aberto — decisão separada
  deste PRD.
- Este documento cobre a visão de produto; a sequência e o detalhe de
  implementação vivem em `plano_global.md` e `plano_desenvolvimento.md`.

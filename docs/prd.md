# PRD — ddf (novo)

## Visão do produto

Bancos relacionais acumulam estrutura — tabelas, colunas, relacionamentos — sem
documentação atualizada. Entender essa estrutura do zero (pra integrar com ela ou
auditá-la) é trabalho manual, repetitivo, e que envelhece rápido. 
A partir de uma única extração de uma fonte de dados, a solução gera múltiplos artefatos
versionáveis e curados por humanos: um **projeto dbt standalone e rodável** (o
pitch) — `dbt_project.yml` + `sources.yml` + modelos de staging + `schema.yml`
já populado com testes de qualidade sugeridos deterministicamente a partir das
métricas extraídas; **documentação Markdown** legível por humano, navegável e
versionável; **contexto denso em JSON** pensado para um agente de IA consumir
a estrutura sem precisar de acesso ao banco; e **curadoria humana via overrides**, com
papel de negócio e regras de tabelas/colunas editáveis em YAML e preservados
entre reexecuções.

## Requisitos funcionais

1. Como usuário, quero conectar a uma fonte de dados informando suas
   credenciais de acesso e extrair a estrutura completa e métricas
   reais de uma vez, para documentar a fonte sem inspeção manual.
2. Quero receber um projeto dbt pronto para rodar, com testes de qualidade já
   sugeridos a partir dos dados reais, para não precisar escrever
   sources/modelos/testes manualmente a cada fonte nova.
3. Quero documentação em Markdown legível e navegável gerada da mesma
   extração, sem custo adicional de trabalho manual.
4. Quero um contexto denso e estruturado, pensado para um agente de IA
   entender a estrutura sem precisar acessar o banco diretamente.
5. Quero curar manualmente o significado de negócio e as regras de tabelas e
   colunas, e que essa curadoria não se perca quando eu reextrair a mesma
   fonte depois.
6. Quero escolher, a cada execução, qual fonte extrair e quais artefatos
   gerar, sem depender de uma versão nova da ferramenta para isso.
7. Quero que, quando algo der errado (fonte indisponível, escopo não
   encontrado, arquivo inválido), eu receba uma mensagem de erro clara
   explicando o que aconteceu, nunca um erro técnico incompreensível.
8. Quero que o tipo de cada coluna extraída preserve a precisão real da fonte
   (escala numérica, tamanho máximo de texto), para que os artefatos gerados
   (como os casts SQL no scaffold dbt) sejam tecnicamente corretos, não
   genéricos.

## Requisitos não funcionais

1. **Confiabilidade:** nenhum artefato é aplicado automaticamente "por trás"
   do usuário — tudo que é gerado fica disponível para revisão antes de
   qualquer uso, e a aprovação do que foi gerado acontece pela revisão normal
   de código do usuário (não existe uma etapa de aprovação separada dentro da
   ferramenta).
2. **Idempotência:** rodar a ferramenta de novo sobre a mesma fonte, sem
   mudanças estruturais nela, nunca apaga ou sobrescreve curadoria humana já
   feita anteriormente. Quando há mudança estrutural (colunas adicionadas,
   removidas ou alteradas), a reextração detecta e avisa explicitamente o
   usuário sobre o que mudou, preservando a curadoria do que permaneceu
   igual.
3. **Confiabilidade dos testes sugeridos:** toda sugestão de teste de
   qualidade tem uma razão identificável e consistente — a mesma métrica
   sempre gera a mesma sugestão, nunca uma sugestão estatística ou
   imprevisível.
4. **Clareza em falhas:** falhas esperadas (fonte fora do ar, escopo ausente,
   arquivo malformado) são sempre comunicadas ao usuário de forma explícita e
   compreensível, nunca como uma falha técnica não tratada.
5. **Extensibilidade:** oferecer suporte a uma nova fonte de dados ou a um
   novo tipo de artefato gerado não deve exigir uma reescrita da ferramenta —
   apenas uma extensão sobre o que já existe.
6. **Qualidade do software entregue:** o produto é mantido com verificação
   automática contínua (testes automatizados) a cada mudança, para reduzir o
   risco de regressão entre versões.
7. **Usabilidade:** o fluxo de uso (da conexão com a fonte até os artefatos
   prontos) é simples o suficiente para ser operado por um usuário técnico sem
   necessidade de ler documentação extensa.
8. **Usabilidade**: A CLI deve ter a capacidade de operar com warnings a cada etapa
   e aguardar resposta do usuário para determinadas ações (confirmar escrita de overrides,
   e teste de conexão com a fonte)
9. **Desempenho:** a extração processa as tabelas da fonte em paralelo (não
   sequencialmente), para que fontes com dezenas ou centenas de tabelas sejam
   extraídas em tempo razoável.

## Restrições do produto

1. **Fontes de dados suportadas na v1: Postgres e MariaDB.** Ambas
   registradas nativamente no wizard (`EXTRATORES_REGISTRADOS`) desde a
   issue #16; suporte a APIs ou arquivos fica para avaliação futura, sem
   prioridade definida ainda.
2. **Não é uma ferramenta de conexão ao vivo/contínua** — não monitora a fonte
   nem expõe um serviço consultável em tempo real (não é um MCP server); é
   uma ferramenta de análise sob demanda que produz artefatos versionáveis.
3. **Sugestão de teste de qualidade limitada a regras determinísticas** —
   não inclui detecção estatística de anomalias nem inferência baseada em
   modelo nesta versão.
4. **Sem camada de consulta via API/web nesta fase** — o produto é consumido
   via linha de comando; uma interface de serviço fica fora de escopo até
   decisão futura.
5. **Sem heurísticas de análise automática avançadas nesta versão** (como
   inferir relacionamentos por convenção de nome ou gerar glossário de
   domínio automaticamente) — fica para avaliação futura.
6. **Testes de integração contra banco real cobrem Postgres e MariaDB**
   (via testcontainers) — extensão da mesma prática de teste acompanha a
   chegada de cada fonte nova, não é antecipada.

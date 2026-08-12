# Issue #75 — fix: corrige achados da banca (arquiteto/PO/engenheiro de dados) sobre a CLI

## Contexto

Rodada da banca de revisão multi-agente (`arquiteto-de-software`,
`po-revisor`, `engenheiro-de-dados`) sobre o estado atual de
`src/ddf/infrastructure/adapters/cli/` (não um diff — auditoria da pasta
inteira, incluindo `etapas/`, `registro/`, `avisos.py`, `prompts.py`,
`validacao.py`, `wizard.py`). Três vereditos: **Aprovado com ressalvas**.

## Decisões tomadas na discussão prévia (antes de implementar)

> **Reordenar o wizard: extrator → teste de conexão → escolha de escopo →
> só então estratégia de amostragem.** Hoje a ordem é estratégia de
> amostragem antes de conhecer a fonte/escala das tabelas
> (`wizard.py:36-41`), forçando o usuário a decidir "1% ou tabela inteira?"
> sem informação real de volume. Confirmado pelo usuário.
> **Aviso de custo de I/O da amostragem deixa de ser texto estático da CLI
> e passa a ser emitido pelo `Extrator`/`EstrategiaDeAmostragem` como
> `Aviso` de domínio.** Hoje só `TabelaInteira` avisa (`registro/
> estrategias.py:75-92`); `PercentualDeLinhas`, a estratégia padrão, não
> avisa que faz varredura sequencial completa independente do percentual
> pedido (limitação documentada em `system_design_doc.md`, issue #56, mas
> que nunca chega ao ponto de decisão do usuário). Confirmado pelo
> usuário — motivo: consistente com o padrão já usado no projeto para
> outros avisos de domínio (`Aviso` emitido pela camada de domínio, não
> hardcoded na CLI).
> **Os dois `sys.exit(1)` de `wizard.py` (lista de tabelas/curadas vazia)
> podem mudar de comportamento.** Como o reordenamento do wizard muda em
> que ponto do fluxo "escopo vazio" é detectável, este ponto entra em
> escopo de análise nesta issue, não é mais um teste a só complementar no
> comportamento atual.

## Escopo desta issue

### Fase 1 — bloqueante: parsing de input numérico sem tratamento de erro ✅ concluída

Achado consensual dos 3 agentes. Commits `b7c74ee` (fix) e `c76ffcc` (test).

- [x] `prompts.py` — novas `numero()`/`numero_opcional()`: reprompt em
      loop até o `conversor` (`int`/`float`) aceitar a resposta, sem deixar
      `ValueError` propagar cru; `numero_opcional` trata resposta em
      branco como `None`
- [x] `registro/estrategias.py:60-72` — percentual e seed passam por
      `prompts.numero`/`numero_opcional`
- [x] `registro/extratores.py:67` — porta do MariaDB passa por
      `prompts.numero`
- [x] Testes cobrindo entrada não numérica nos 3 pontos (`test_prompts.py`,
      `test_estrategias.py`, `test_extratores.py`, via as funções privadas
      `_construir_percentual_de_linhas`/`_construir_extrator_mariadb`)

### Fase 2 — reordenamento do wizard + aviso de custo como `Aviso` de domínio ✅ concluída

Commit `9fd4e43` (aviso de domínio, já commitado). Reorder + `_sair_se_vazio`
ainda não commitados nesta sessão — ver sugestão de commits abaixo.

- [x] Aviso de custo de full-scan do `PercentualDeLinhas` movido para
      `construir_metadados_de_amostra` (helper agnóstico de fonte
      reaproveitado por `ExtratorPostgres`/`ExtratorMariaDB`) — emitido a
      cada extração de tabela via essa estratégia, citando `total_linhas`
      real; segue o mesmo mecanismo de agrupamento/colapso já usado pelo
      `Aviso` de `tamanho_amostra > total_linhas` (issue #56). Não
      implementado no Port `EstrategiaDeAmostragem` porque esse Port já
      documenta explicitamente que custo de execução é responsabilidade de
      cada Extrator, não dele. Docstring de `PercentualDeLinhas` atualizada.
      5 testes existentes (Postgres/MariaDB unit + integração) ajustados
      para o novo Aviso adicional.
      **Decisão revisitada:** `TabelaInteira` mantém só a confirmação
      interativa bloqueante que já tinha (`_construir_tabela_inteira`,
      "Continuar?") — não ganha Aviso de domínio adicional. Confirmado
      pelo usuário: a confirmação bloqueante já é mais forte que um Aviso
      passivo, e é a estratégia mais arriscada (sem limite de tamanho).
- [x] `wizard.py` — nova ordem: escolher extrator → testar conexão →
      escolher escopo(s) → escolher estratégia de amostragem → resto do
      fluxo inalterado. Trava arquitetural encontrada e resolvida:
      `ConfiguracaoDeExtracao.estrategia` era exigida no construtor do
      Extrator, o que forçava a estratégia a ser escolhida antes de
      conectar. Resolvida tornando `estrategia` opcional (`| None = None`)
      — decisão do usuário — com `conectar()` construindo o Extrator sem
      estratégia e `configurar_amostragem(configuracao)` atribuindo-a
      depois, no mesmo objeto (mutação, mesma referência que o Extrator já
      guarda). `ExtratorPostgres.extrair_tabela`/`ExtratorMariaDB.
      extrair_tabela` ganham guarda no topo (`Falha` explícita se
      `estrategia is None`) em vez de deixar `AttributeError` propagar.
      Testes ajustados: `test_extracao.py` (assinaturas novas de
      `conectar()`/`configurar_amostragem()`), `test_wizard_end_to_end.py`
      (ordem dos `select` trocada).
- [x] Volume real das tabelas (`total_linhas`) permanece indisponível antes
      da escolha de estratégia — só é conhecido durante `extrair_tabela`,
      não há chamada de catálogo leve que o exponha antes. O ganho do
      reorder é ver fonte/escopo antes de escolher %, não o volume em si;
      exposição de `total_linhas` fica de fato dependente da Fase 3
      (eliminar `_contar_tabelas` duplicado) — não resolvido aqui.
- [x] Reavaliados os dois `sys.exit(1)` de `wizard.py` — comportamento
      mantido (`OrquestradorParalelo.extrair`/`aplicar_sobrescritas` nunca
      devolvem `Falha`, sempre Sucesso mesmo com lote vazio; o wizard é o
      único ponto que decide que lote vazio não deve seguir adiante).
      Extraído `_sair_se_vazio(itens, mensagem)` (2 call sites, elimina
      duplicação e torna a lógica testável isoladamente). Testes novos:
      `test_wizard.py` (unitário, os dois ramos de `_sair_se_vazio`) e
      `test_wizard_end_to_end.py::test_wizard_sem_tabela_extraida_sai_com_codigo_1`
      (integração via CliRunner, extração vazia de ponta a ponta).

### Fase 3 — sugestões de qualidade (não bloqueantes) ✅ concluída

- [x] `registro/extratores.py:54-76` — Postgres agora pergunta host/porta/
      banco/usuário separados, com senha via `prompts.senha()` (mascarada),
      igual MariaDB, em vez de uma connection string inteira em texto
      claro. DSN montada internamente com `urllib.parse.quote` em usuário/
      senha/banco (evita URL malformada se algum contiver `@`, `:`, `/`,
      `%`). Testes novos: caminho feliz (senha mascarada) e borda
      (caracteres especiais viram %-encoded corretamente).
- [x] `etapas/extracao.py:79-96` (`_contar_tabelas`) — removida. `Port
      OrquestradorDeTabelas.extrair` ganhou parâmetro opcional
      `ao_conhecer_total: Callable[[int], None] | None`, chamado por
      `OrquestradorParalelo` logo após a listagem interna terminar, com o
      nº real de pares a extrair — elimina a 2ª listagem de catálogo por
      completo (não só mitiga). `prompts.progresso_paralelo` passou a
      devolver `tuple[callback_progresso, callback_definir_total]`; os 2
      call sites de `curadoria.py` (total já conhecido via `len(tabelas)`)
      descartam o 2º elemento. Testes novos: `test_orquestrador_paralelo.py`
      (`ao_conhecer_total` com falha parcial de listagem — só conta pares
      que de fato serão extraídos), `test_prompts.py` (total definido após
      a criação), `test_extracao.py` (fração exibida vem do orquestrador).
- [x] `validacao.py:78-87` — mensagens de erro de dependência ausente
      (`produz`/`requer`) e de ciclo detectado agora citam o rótulo de
      registro (ex.: "Markdown"), não mais `type(instancia).__name__`
      (ex.: "GeradorFake"/"GeradorDbt"). `validar_dependencias` mudou de
      assinatura — recebe `dict[str, Analisador]`/`dict[str, Gerador]`
      (nome de registro -> instância) em vez de listas soltas, e monta um
      mapa `id(instância) -> nome` internamente (`_rotulo`, com fallback
      pro nome da classe se a instância não estiver no dict). `etapas/
      analise.py::validar_selecao` passa `ANALISADORES_REGISTRADOS` direto
      e monta o dict de Geradores escolhidos, em vez de converter pra
      listas antes de chamar. Toda a suíte de `test_validacao.py`
      reescrita para o novo formato de entrada, assertions trocadas de
      nome de classe pra rótulo de registro.
- [x] `validacao.py:51-55` (`_mapear_produtores`) — dict comprehension com
      `for` aninhado virou loop explícito (resolvido junto da mudança
      acima, mesmo arquivo).
- [x] `etapas/geracao.py:13-17` — `_SUGESTOES_DE_DESTINO` (dicionário fixo
      por nome) removido. Substituído por `_slugificar` — conversão
      genérica CamelCase → snake_case (2 regex, idioma padrão) — sem
      precisar conhecer os nomes dos Geradores nativos de antemão nem
      cadastrar exceção pra cada um. "ContextoDeIA" → "contexto_de_ia",
      "Markdown" → "markdown", e qualquer nome futuro (nativo ou de plugin
      de terceiro) sem exceção manual. Não tocou o Port `Gerador` nem o
      registro — mudança contida em `geracao.py`. Teste de borda trocado
      pra cobrir a conversão genérica em vez do fallback antigo.
- [x] `tests/unit/.../cli/registro/test_{analisadores,estrategias,
      extratores,geradores}.py` — `test_estrategias.py`/`test_extratores.py`
      já ganharam "Borda" de verdade como efeito colateral de itens
      anteriores desta fase (`_construir_percentual_de_linhas`/
      `_construir_extrator_postgres`). `test_analisadores.py`/
      `test_geradores.py` continuam só com 2 categorias, deliberadamente
      sem docstring explicando o porquê — usuário considerou desnecessário
      (são wrappers de 1 linha sobre `registrar_ou_falhar`, sem caso limite
      de domínio genuíno a mais; achado fraco o suficiente pra não precisar
      de comentário).

### Fase 4 — `connect_timeout` ausente em `ExtratorPostgres` ✅ concluída

Fora da pasta `cli/`, mas decidido pelo usuário resolver dentro desta
mesma issue: host inacessível por firewall (pacotes descartados, não
recusados) trava `_testar_conexao` por tempo indefinido — o SO só desiste
depois de um timeout de TCP que pode passar de um minuto, antes de a CLI
sequer mostrar a primeira mensagem de erro/retry.

- [x] `ExtratorPostgres.__init__` ganhou `connect_timeout: int = 50`
      (segundos até desistir de abrir a conexão TCP inicial — parâmetro
      `connect_timeout` do libpq), repassado ao `ThreadedConnectionPool`
      junto de `dsn`/`maxconn`. Valor padrão definido pelo usuário (50s,
      não os 10s inicialmente sugeridos). Não configurável pelo wizard —
      `_construir_extrator_postgres` não passa o parâmetro, usa o default,
      mesmo padrão já usado para `max_conexoes` (também não exposto na CLI).
      `statement_timeout` (query longa em execução) não implementado — é
      um problema diferente do diagnosticado (conexão inicial travada),
      fora do escopo deste achado específico.
- [x] Testes: `test_primeiro_uso_cria_pool_com_parametros_corretos`/
      `test_max_conexoes_padrao_dimensiona_pool_com_oito` ajustados pro
      novo kwarg; teste novo `test_connect_timeout_customizado_e_repassado_
      ao_pool` (borda: override do valor default é repassado ao pool).

### Fase 5 — 2ª rodada da banca sobre o diff completo (`development...HEAD`) ✅ concluída

Banca (arquiteto-de-software, po-revisor, engenheiro-de-dados) revisou o
diff inteiro das Fases 1-4 antes de fechar a issue. Veredito: **Aprovado
com ressalvas** nas 3 lentes. Achados convergentes e de trade-off, todos
resolvidos a pedido do usuário ("trabalhar em todos os achados nesta
issue mesmo"):

- [x] **Mensagem de Aviso de custo sem identificador de tabela**
      (engenheiro de dados) — `construir_metadados_de_amostra` ganhou
      parâmetro `identificador_tabela: str`, citado nas duas mensagens de
      Aviso (custo de full-scan e divergência amostra/total_linhas), igual
      ao padrão já usado em `construir_colunas_fk`. Sem isso, os 3
      exemplos que `avisos.py` mostra antes de colapsar por contagem
      ficavam anônimos — impossível saber qual tabela paga o custo em um
      banco com muitas tabelas. Os 2 call sites (`extrator_postgres.py`,
      `extrator_mariadb.py`) passam `f"{schema}.{tabela}"`.
- [x] **Guarda `estrategia is None` duplicada verbatim** (arquiteto) —
      centralizada em `ConfiguracaoDeExtracao.estrategia_obrigatoria() ->
      Resultado[EstrategiaDeAmostragem]`, chamado pelos dois
      `extrair_tabela` em vez de cada Adapter reimplementar o mesmo `if`.
      Fecha o risco real: nada garantia que um 3º Extrator (issue #67)
      lembraria de replicar o guard.
- [x] **Sem teste cobrindo a `Falha` do guard** (arquiteto) — testes
      novos em `test_configuracao_de_extracao.py` (`estrategia_obrigatoria`
      isolada: caminho feliz, erro esperado, borda de atribuição tardia) e
      um teste por Extrator (`test_extrair_tabela_sem_estrategia_
      configurada_retorna_falha`) em `test_extrator_postgres.py`/
      `test_extrator_mariadb.py`.
- [x] **Documentação de arquitetura desatualizada** (PO + arquiteto,
      convergência forte) — `docs/system_design_doc.md` (ordem do wizard
      na seção 8, nova Decisão de Arquitetura 13) e `docs/low_level_design.md`
      (assinatura de `ConfiguracaoDeExtracao`, `OrquestradorDeTabelas.
      extrair`/`OrquestradorParalelo.extrair` com `ao_conhecer_total`,
      as 14 etapas renumeradas, `validar_dependencias` com dicts,
      `ExtratorPostgres.__init__` com `connect_timeout`) atualizados.
      `docs/prd.md` NFR8 ("teste de string de conexão" → "teste de conexão
      com a fonte") ajustado — texto desalinhado desde que Postgres deixou
      de usar uma única connection string.
- [x] **Perda de `sslmode`/parâmetros libpq no Postgres** (engenheiro de
      dados, decisão) — campo opcional "Parâmetros extra de conexão"
      adicionado a `_construir_extrator_postgres`, anexado como query
      string à DSN quando preenchido. Cobre Postgres gerenciado (RDS,
      Azure Database, PgBouncer) que costuma exigir `sslmode=require`,
      sem voltar à connection string livre inteira.
- [x] **MariaDB sem `connect_timeout` explícito** (arquiteto perguntou,
      engenheiro confirmou via doc oficial do `pymysql`: já era o default
      do driver, 10s — não era bug). Declarado explicitamente mesmo assim,
      por simetria de leitura do código com `ExtratorPostgres` — mesmo
      valor (10s), zero mudança de comportamento.
- [x] **`progresso_paralelo` retornando tupla posicional** — agora devolve
      `Progresso(NamedTuple)` com campos nomeados (`callback`,
      `definir_total`); retrocompatível com desempacotamento por posição
      nos 3 call sites existentes (nenhum precisou mudar). Teste novo
      garantindo acesso por nome.
- [x] **`host` sem tratamento para IPv6 literal na DSN do Postgres** —
      `_formatar_host` envolve IPv6 literal em colchetes (`[::1]:porta`);
      hostname (ex.: endpoint AWS RDS) e IPv4 passam intactos — confirmado
      que RDS nunca expõe IPv6 bruto, sempre hostname, então não afeta o
      caso comum de uso da ferramenta. Testes novos (`_formatar_host`
      isolado + `_construir_extrator_postgres` com host IPv6).
- [ ] **`numero()`/`numero_opcional()` como par quase-duplicado** — avaliado
      e **não fundido**: a fusão exigiria retorno `_Numero | None` mesmo
      nos 3 call sites que hoje recebem `_Numero` puro (porta, percentual),
      piorando a tipagem estrita pra eliminar ~4 linhas duplicadas. Mantido
      como está.

## Testes

- [x] Fase 1: caminho feliz, erro esperado (entrada não numérica) e borda
      por ponto de entrada (percentual, seed, porta)
- [x] Fase 2: teste de integração do wizard cobrindo a nova ordem de
      etapas; teste(s) cobrindo os dois ramos de saída antecipada
      (`sys.exit`) conforme decisão de comportamento tomada; teste do novo
      `Aviso` de custo emitido pelas duas `EstrategiaDeAmostragem`
- [x] Fase 3: casos novos nos testes já existentes dos arquivos tocados
- [ ] Fase 4: teste de timeout de conexão do `ExtratorPostgres`
- [x] `mypy --strict` + `ruff` limpos, `pytest` completo (unit +
      integration) verde a cada passo (433 testes)

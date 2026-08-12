# Issue #116 — Ajustes de UX no wizard

## Fase 1 — barra de progresso mostra a tabela errada sob paralelismo

Achado real: com `max_trabalhadores=8`, o callback `progresso` só dispara na
conclusão de um item (`as_completed`) — nunca há sinal de "começou". Numa
extração com uma tabela outlier (`token_acesso`, ~40x maior que a 2ª maior
do schema testado), a última tabela pequena concluída ficava exibida na
tela enquanto a grande processava em segundo plano — o usuário confundiu a
tabela pequena (já pronta) com a causa da lentidão.

**Tentativa revertida (usuário, 2026-08-06):** implementamos um callback
`inicio` opcional/thread-safe no Port `OrquestradorDeTabelas`, mostrando o
conjunto de tabelas "em andamento" em vez da última concluída. Funcionou
para poucas tabelas, mas quebrou visualmente em escala real (~122 tabelas
em paralelo): a lista de identificadores em andamento cresce até quebrar
em múltiplas linhas do terminal, e `\r` só retorna ao início da *linha
visual* atual, não da linha lógica inteira — `\x1b[K` não alcança as linhas
de cima, gerando um log cascateado de trechos repetidos (capturado em
screenshot real pelo usuário). Revertido por completo — `Progresso`/
`progresso_paralelo` voltaram a ter só `callback`/`definir_total`, o Port
e `OrquestradorParalelo` voltaram a não ter `inicio`, e a barra volta a
mostrar só a última tabela concluída (comportamento original, pré-#116).

Direção futura (não implementada agora): uma barra de progresso real de
blocos preenchidos (largura fixa, como a referência Oxide `███████░░░░░`),
não uma lista de identificadores que cresce sem limite — fica para uma
rodada futura da issue, não reabrir a abordagem de "em andamento" por
nome de tabela.

- [x] ~~`domain/ports/orquestrador_de_tabelas.py` — `inicio` opcional~~
      revertido
- [x] ~~`orquestrador_paralelo.py` — `inicio` de dentro do worker~~
      revertido
- [x] ~~`prompts.py`/`cli/etapas/*.py` — set "em andamento"~~ revertido
- [x] Barra de progresso real — implementada em `prompts.py::progresso_paralelo`
      (`_barra`): retângulos verticais `▮`/`▯` (contorno no vazio, fundo real
      do terminal), ciano (`COR_DESTAQUE`) no preenchido, largura dinâmica
      igual à linha "mensagem (N/total)" acima (termina sob o `)` de
      fechamento). Pesquisa de prior art e implementação pelo agente
      `especialista-ux-terminal`, validada com captura `pty` real.

## Fase 2 — espaçamento/consistência de prompts e mensagens

Levantado de um log real de execução. Trabalho feito diretamente com o
agente `especialista-ux-terminal`.

Decisão fechada (usuário): sem menu numerado com loop "volta pro menu" —
o ddf é pipeline linear de checkpoints fixos, roda uma vez e termina.
`questionary.select`/`checkbox` (arrow-key + fuzzy filter) continuam como
estão. Das referências visuais (bluesnoop/ALATRIX/Oxide), aproveitamos só
a "casca": separadores, cabeçalhos de seção, caixas de resumo, prefixos de
status — aplicados a um fluxo sequencial.

Auditoria completa do agente (achados, arquivo:linha, prior art) registrada
nesta sessão — recomendações por impacto:

- [x] **[Alto impacto]** `cabecalho_etapa(numero, total, titulo)` em
      `prompts.py`, aplicado nos checkpoints visíveis de `wizard.py` (não as
      14 etapas documentadas em `system_design_doc.md` — várias são
      agrupadas por não terem pergunta nova ao usuário entre elas; decisão
      confirmada com o usuário, não reabrir). Total foi 12, depois 11 —
      "Validar analisadores e geradores" perdeu o cabeçalho próprio (não
      produzia nenhuma saída visível no caminho feliz, era um checkpoint
      vazio) e passou a rodar dentro da etapa "Escolher geradores".
- [x] `linha_de_decisao(rotulo, valor)` em `prompts.py`, inspirada no
      resumo em árvore do shell da Oxide (`├─`) — aplicada inicialmente em
      5 pontos de escolha (Fonte/Amostragem em `extracao.py`, Geradores em
      `analise.py`, Escopos/Destino em `wizard.py`). Sempre `├─`, nunca
      `└─` — as decisões não formam um bloco fechado como na referência
      (intercaladas por cabeçalhos e blocos de processamento), então `└─`
      mentiria "essa foi a última decisão". **Removida depois de Escopos**
      (usuário, 2026-08-06) **, Amostragem** (mesma sessão) **, Geradores e
      Destino** (usuário, 2026-08-07) — `questionary` já ecoa a resposta
      escolhida em `COR_DESTAQUE` inline (`select`/`checkbox`/`text` via
      `_ESTILO`), então a árvore ali era redundante ("só a Escolha em azul
      já é suficiente"). Sobrevive só na árvore de conexão
      (`registro/extratores.py`: Fonte/Host/Porta/Banco/Usuário/Senha),
      onde o bloco fechado e contíguo de decisões (sem nada entre elas)
      continua justificando o resumo visual.
- [ ] ~~Responsividade à largura do terminal~~ — tentado e **revertido a
      pedido do usuário**: `largura_disponivel()` (`shutil.get_terminal_
      size()`, clamp 40-100) em `cabecalho_etapa`, e `_BANNER_COMPACTO`
      como fallback do banner ASCII abaixo de 91 colunas. Voltou à largura
      fixa de 70 (`cabecalho_etapa`) e ao banner único (`wizard.py`). Não
      reabrir sem novo pedido explícito.
- [x] **[Alto impacto]** Cor semântica de erro/aviso — `COR_ERRO`/
      `COR_AVISO` novas em `prompts.py`, aplicadas em todo "Erro:"/
      "Falha..." do wizard (`avisos.py`, `curadoria.py`, `geracao.py`,
      `estrategias.py`, `extracao.py`, `prompts.py`)
- [x] **[Alto impacto]** `✓`/`COR_SUCESSO` hoje só em `extracao.py` —
      estendido para `curadoria.py` (skeletons/sobrescritas),
      `analise.py` (análise concluída), `geracao.py` (artefato escrito)
- [x] **[Polimento]** avisos sem destaque visual em `avisos.py` — bloco de
      `exibir_avisos` (cabeçalho `[origem] N aviso(s):` e cada linha) agora
      sai em `COR_AVISO`
- [x] **[Médio]** `selecionar` usado para decisão binária em
      `extracao.py` (era "Tentar novamente"/"Sair") — trocado por
      `confirmar`, mesmo padrão de `geracao.py::confirmar_execucao`
- [x] **Não estava no backlog original, pedido do usuário (2026-08-07):**
      ao **confirmar** "Tentar novamente?" após uma
      falha de conexão, `_testar_conexao` agora reconstrói o `Extrator` do
      zero (pergunta host/porta/usuário/senha de novo) em vez de reusar a
      mesma instância com os mesmos parâmetros — antes, uma senha digitada
      errada nunca tinha chance de funcionar no retry.
- [x] **Não estava no backlog original, pedido do usuário (2026-08-07):**
      Aviso de custo da estratégia "Percentual de linhas" (varredura
      completa da tabela, independente do percentual) saía **por tabela**
      via `Aviso` em `construir_metadados_de_amostra` — redundante em
      dezenas/centenas de tabelas, já que o fato é estrutural e idêntico
      nos dois Extratores (Postgres/MariaDB), não muda por tabela. Movido
      pra um aviso único, na escolha da estratégia
      (`cli/registro/estrategias.py::_construir_percentual_de_linhas`),
      mensagem encurtada, sem travessão embutido, com o símbolo de aviso
      (`▲`, mesma família geométrica de `▮`/`▯`) e `COR_AVISO`. Tocou a
      camada de Extraction Adapters (`construir_metadados_de_amostra.py`,
      `PercentualDeLinhas`), não só `cli/` — fora do escopo do agente de
      UX, feito diretamente. `RequisicaoPorFaixa` (estratégia "Amostragem
      por faixa") não foi tocada — o Aviso de viés de cluster dela cita
      dados por tabela (mecanismo real usado), não é um fato genérico
      repetido.
- [x] **Não estava no backlog original, pedido do usuário (2026-08-08):**
      `_construir_percentual_de_linhas` (item acima) recebeu `print()` antes
      do aviso — a mensagem saía colada na resposta da pergunta "Seed", sem
      espaçamento, diferente do resto do módulo `cli/` (`extracao.py`,
      `curadoria.py` já têm essa linha em branco antes de todo
      `imprimir_destacado` que segue uma pergunta/ação). Não abriu um padrão
      novo, só completou um que já existia — os outros dois avisos de
      estratégia (`_construir_tabela_inteira`/`_construir_amostragem_por_
      faixa`) não precisam do mesmo tratamento porque o aviso ali *é* o
      texto da própria pergunta `confirmar(...)`, que já tem sua linha em
      branco embutida.
- [x] **Não estava no backlog original, pedido do usuário (2026-08-08):**
      Mesmo padrão redundante identificado na estratégia "Amostragem por
      faixa" — o Aviso de viés de cluster (`RequisicaoPorFaixa`, em
      `construir_metadados_de_amostra`) saía **por tabela** com texto
      idêntico (só o nome da tabela mudava; no MariaDB, `k_faixas` também
      variava, mas era incidental, não acionável). Removido de
      `construir_metadados_de_amostra.py` (parâmetro `descricao_vies_por_
      faixa` eliminado, chamadas em `extrator_postgres.py`/`extrator_
      mariadb.py` simplificadas) — a mensagem já existente em `_construir_
      amostragem_por_faixa` (via `prompts.confirmar`, motor-agnóstica de
      propósito, já que o Extrator ainda não foi escolhido nesse ponto do
      wizard) passa a ser o único aviso, sem precisar de código novo ali.
      `docs/system_design_doc.md` e `docs/low_level_design.md` atualizados
      para não afirmar mais "Aviso por tabela"; testes unitários e de
      integração (Postgres/MariaDB) ajustados. O Aviso de "gaps densos na
      PK" (condicional, `tamanho_amostra < 0.5 * n_pedido`) e o de fallback
      pra probabilístico (PK não elegível) continuam por tabela — são
      condições reais que variam por execução, não fatos estruturais
      repetidos.
- [ ] ~~**[Médio]** `print()` de blank-line pós-progresso duplicado em vários
      lugares (`extracao.py`, `curadoria.py`, `analise.py`) — encapsular no
      `finally` de `ampulheta`/`barra_indeterminada`~~
- [x] **[Médio]** símbolo ASCII vs emoji sem regra declarada — pesquisa do
      agente `especialista-ux-terminal` (prior art: `questionary` não
      define família própria; `rich`/`ora`/`cli-spinners`/`gh` convergem
      pra texto Unicode simples — largura fixa, cor controlável via ANSI —
      nunca emoji real em indicador de status/progresso, que tem largura
      variável e cor fixa fora do controle do terminal). `✓`/`▮`/`▯`/
      `├─`/`└─` já eram texto puro; só `⏳`/`⌛` (spinner de `ampulheta`) e
      `⏱️` (prefixo de duração) eram emoji reais — trocados: spinner agora
      é braille dots (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`, mesmo default de `rich`/`cli-spinners`),
      prefixo de duração removido (`duração: Xs`, sem ícone, padrão `gh`)
- [x] **[Médio]** duração reportada só em `extracao.py` — estendida a
      `curadoria.py::aplicar_sobrescritas` e `analise.py::analisar` (mesmo
      formato `⏱️  duração: Xs`)
- [ ] ~~**[Polimento]** cancelamento silencioso — sem "Cancelado." antes de
      `sys.exit(0)` nos 5 pontos de `prompts.py`~~
- [ ] ~~**[Deixado por último]** redraw duplicado ao redimensionar o terminal
      durante um prompt (`selecionar`/`escolher_multiplos`) — reportado pelo
      usuário com screenshot real (lista de escopos, 2026-08-06).
      Reproduzido de forma controlada com `pty` + `SIGWINCH` forçado: o
      problema **não** é o `"\n"` embutido em `instruction=` (usado para o
      espaçamento pergunta→lista) — acontece igual sem ele. É bug do
      `prompt_toolkit`: quando pergunta+instrução quebra em mais de uma
      linha visual, o redraw pós-resize não limpa direito as linhas
      antigas, deixando fragmentos da renderização anterior colados na
      nova. O `"\n"` só piora a chance (uma linha a mais facilita estourar
      a largura). Mitigação possível, não solução: reverter o `"\n"` e
      encurtar as instruções reduz a chance de quebra, mas não elimina em
      terminais estreitos — é limitação da lib, não do nosso código.
      Resolver por último, depois do resto do backlog de Fase 2.~~

Riscos fora do escopo do agente de UX, já resolvidos:
- (Arquiteto) menu numerado — descartado, decisão do usuário acima.
- (PO) numeração 12 vs. 14 — decisão do usuário: manter 12.

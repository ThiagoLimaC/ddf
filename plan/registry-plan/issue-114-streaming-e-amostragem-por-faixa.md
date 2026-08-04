# Issue #114 — streaming de amostragem + amostragem por faixa (opt-in)

Plano completo revisado em `/home/dev/.claude/plans/twinkly-churning-wilkinson.md`
(sessão de planejamento). Banca de revisão completa (arquiteto-de-software +
engenheiro-de-dados + po-revisor) rodada sobre o plano antes da
implementação — exigência explícita da própria issue por ser mudança
estrutural cross-context (amplia a união fechada `RequisicaoDeAmostragem`),
mesmo critério de #44/#89/#95/#105. Engenheiro de dados retornou veredito
inicial **bloqueante** (2 achados, validados empiricamente contra Postgres
16 e MariaDB 11 reais); ambos resolvidos no plano antes do código. Achados
incorporados abaixo.

## Contexto

Investigação de trava/lentidão na extração contra um Postgres real de
produção (122 tabelas). `token_acesso` (4.118.390 linhas/778MB, ~40x maior
que a 2ª maior tabela do mesmo schema) reproduziu o sintoma relatado: RSS
de pico ~900MB isolado, mesmo com `PercentualDeLinhas(10)` (default do
wizard, não só `TabelaInteira`). Causa raiz: `cursor.execute()` sem cursor
nomeado (psycopg2) ou sem `SSCursor` (pymysql) materializa o resultset
inteiro client-side antes de qualquer `fetch*` — comportamento padrão dos
dois drivers. Substitui a issue #113 (premissa incorreta: achava que só
`TabelaInteira` sofria disso).

## Achados bloqueantes da banca e resolução adotada

- **B1 — cursor nomeado do Postgres represa `VACUUM` no banco inteiro**
  (não só na tabela lida) enquanto a transação do streaming estiver
  aberta — confirmado empiricamente pelo engenheiro de dados. Resolução:
  streaming só ativa acima de um limiar (linhas OU bytes estimados —
  ver B1 abaixo), tabelas pequenas continuam com `fetchall()` direto.
  Sem teste de carga concorrente de escrita (infraestrutura fora do
  escopo pragmático da issue) — risco documentado como limitação aceita
  em `docs/low_level_design.md`, não validado por teste.
- **B2 — "range por PK" no MariaDB com `LIMIT n` grande devolve uma única
  janela contígua**, não uma amostra espalhada (a técnica canônica de
  mercado é `LIMIT 1` repetido, inviável em performance para `n` na casa
  de milhares). Resolução: `K` faixas contíguas menores sorteadas
  independentemente (candidato `K=10`, calibrado pelo benchmark),
  aproximando o comportamento de blocos espalhados do `TABLESAMPLE
  SYSTEM` do Postgres. Aviso de viés do MariaDB é **distinto** do
  Postgres — explica o trade-off de origem (custo de amostra
  verdadeiramente aleatória por PK), não só o efeito.

## Nomenclatura da estratégia nova

Padronizar as 3 Estratégias existentes (`PercentualDeLinhas`/
`TabelaInteira`/nova) e as 3 Requisições (`AmostragemProbabilistica`/
`AmostragemIntegral`/nova) sob um único prefixo consistente foi cogitado
e **descartado nesta issue** — o blast radius (~55 arquivos entre `src/`,
`tests/` e `docs/`, puro rename sem ganho funcional) não se justifica
agora; fica registrado como possível reabertura de escopo futura, não
perdido.

Escopo real desta issue: só o par novo precisa de nome, sem colidir com
o que já existe (`PercentualDeLinhas`/`TabelaInteira` na camada de
Estratégia, `AmostragemProbabilistica`/`AmostragemIntegral` na camada de
Requisição — nenhum dos dois muda):

- Estratégia (`EstrategiaDeAmostragem`): `AmostragemPorFaixa`.
- Requisição (`RequisicaoDeAmostragem`, 3º membro da união fechada):
  `RequisicaoPorFaixa` — nome deliberadamente diferente do da Estratégia
  (não `AmostragemPorFaixa` nos dois lados), para não reabrir a mesma
  ambiguidade Estratégia/Requisição que a revisão do arquiteto pediu
  para evitar.

## Decisões fechadas com o usuário (fora da banca)

- Limiares de ativação do streaming (linhas e bytes) e `K` faixas do
  MariaDB: candidatos no plano, valores finais **calibrados pelo
  benchmark**, não fixados agora.
- Teste de carga concorrente de escrita: removido do escopo (sem
  workload de escrita disponível) — risco de B1 fica documentado, não
  testado.
- Tamanho de lote do streaming: calibrado por **bytes estimados** (não
  contagem fixa de linhas) — `pg_stats.avg_width` (Postgres, query nova)
  / `information_schema.tables.avg_row_length` (MariaDB, zero query
  nova) somados ao round-trip de metadados já existente por schema.

## Checklist de execução

- [x] 0. Este arquivo (registry-plan).
- [x] 1. `RequisicaoDeAmostragem` (3º membro: `RequisicaoPorFaixa`) +
      `EstrategiaDeAmostragem` concreta `AmostragemPorFaixa`
      (`extractors/estrategias/amostragem_por_faixa.py`) — contrato, sem
      lógica de SQL ainda. `mypy --strict` força `case` novo em todo
      `match` existente.
- [x] 2. `ExtratorPostgres`: dispatch de `RequisicaoPorFaixa`
      (`TABLESAMPLE SYSTEM ... REPEATABLE`) + `case` novo em
      `construir_metadados_de_amostra` (Aviso de viés, texto próprio).
- [x] 3. `ExtratorMariaDB`: `_elegibilidade_de_pk_para_faixa` (função
      pura em `_construcao.py`, testável isolada) + dispatch com `K`
      faixas (PK elegível) + fallback `RAND() <= p` (PK não elegível,
      Aviso distinto) + Aviso condicional de gaps densos
      (`tamanho_amostra < 0.5 * n_pedido`).
  - Decisão técnica: no fallback (PK não elegível), `requisicao_efetiva`
    vira `AmostragemProbabilistica` (não uma variação de
    `RequisicaoPorFaixa`) — reaproveita o `case` já existente em
    `construir_metadados_de_amostra`, que emite sozinho o Aviso de
    "varredura sequencial completa" (correto: o fallback usa
    `WHERE RAND(seed) <= p`, o mesmo SQL de `PercentualDeLinhas`). O
    Extrator só soma um segundo Aviso explicando por que caiu no
    fallback. Evita duplicar a mensagem de viés errada (cluster) num
    caminho que não tem mais viés de cluster nenhum.
  - `K = 10` faixas via `UNION ALL` de sub-consultas
    `(SELECT ... WHERE pk >= FLOOR(RAND(seed_k) * max_pk) ORDER BY pk
    LIMIT n/K)`, `seed_k = seed_usado + k` — evita `LIMIT 1` repetido
    `n` vezes (um round-trip por linha, inviável). `MAX(pk)` lido uma
    vez por tabela (1 round-trip extra), não repetido por faixa.
- [x] 4. Estimativa de largura média de linha por tabela: query nova
      `pg_stats.avg_width` (Postgres, agregada por schema) + coluna
      `avg_row_length` adicionada ao `_TOTAL_LINHAS_SQL` existente
      (MariaDB, zero query nova) — populam `_MetadadosDoSchema`.
      `LARGURA_MEDIA_PADRAO_BYTES` (fallback) vive em cada `_queries.py`
      (Postgres e MariaDB têm sua própria cópia, valor igual mas fonte de
      dado e motivo de ausência diferentes por motor) — sem arquivo
      `comum/` só para uma constante sem lógica associada.
- [x] 5. Helpers `calcular_tamanho_lote` (bytes → nº de linhas por lote,
      com clamps mínimo/máximo) e `ler_amostra_em_lotes` (loop
      `fetchmany` + `pl.concat`, cursor Protocol estrutural) — os dois
      num único arquivo `extractors/comum/ler_amostra_em_lotes.py`
      (decisão do usuário: um helper calcula o parâmetro que o outro
      consome, mesmo fluxo de streaming — não justificam dois arquivos).
      Compartilhados pelos dois Extratores, ainda não usados por eles
      (fiação real vem nos itens 6/7).
- [x] 6. Streaming no `ExtratorPostgres`: `_conexao(autocommit: bool =
      True)`, cursor nomeado + `itersize` acima do limiar
      (linhas OU bytes), `commit()` explícito antes do `putconn`.
  - `deve_usar_streaming`/`_LIMIAR_LINHAS_STREAMING`/
    `_LIMIAR_BYTES_STREAMING` (candidatos: 100.000 linhas / 100MB, a
    calibrar pelo benchmark) ficaram no mesmo arquivo
    `extractors/comum/ler_amostra_em_lotes.py` do item 5 — mesma decisão
    do usuário: os três formam um único fluxo de decisão (se, quanto,
    como ler em lotes).
  - `_conexao` não commita sozinha: quem pede `autocommit=False` é
    responsável por `conexao.commit()` no caminho de sucesso, antes do
    `with` terminar — no caminho de erro, o `rollback()` automático do
    `ThreadedConnectionPool.putconn` cobre a limpeza (achado do
    arquiteto/engenheiro de dados, documentado no docstring).
  - Extraído `_nomes_colunas(cursor)` (nível de módulo): reuso real
    entre os dois branches (streaming/não-streaming), não indireção
    decorativa.
- [x] 7. Streaming no `ExtratorMariaDB`: `SSCursor` acima do mesmo
      limiar, tratamento de exceção no meio do loop (fecha cursor antes
      de propagar).
  - Mesmo `deve_usar_streaming`/`calcular_tamanho_lote`/
    `ler_amostra_em_lotes` do item 6, reaproveitados sem mudança —
    reforça que o cálculo é agnóstico de motor.
  - Fechamento determinístico do cursor antes de propagar exceção
    (achado do engenheiro de dados: `SSCursor` deixado para o GC fechar
    via `__del__` gera `AttributeError` silenciosamente engolido) já é
    garantido pelo `with cursor_bruto as cursor:` existente — não
    precisou de `try/except` manual, o protocolo de context manager já
    chama `cursor.close()` no `__exit__` antes de qualquer exceção
    propagar pra fora do bloco.
- [x] 8. CLI (`cli/registro/estrategias.py`): registro da nova
      estratégia no wizard, nome curto + `prompts.confirmar(...)` com
      o trade-off em linguagem de efeito.
  - `"Amostragem por faixa"` — mesmo padrão de nome curto e neutro de
    `"Percentual de linhas"`/`"Tabela inteira"`, sem jargão ("viés de
    cluster") no nome do menu, só na mensagem de confirmação.
  - `_construir_amostragem_por_faixa` segue o mesmo esqueleto de
    `_construir_tabela_inteira` (confirmação primeiro, `sys.exit(0)` se
    recusada) + `_construir_percentual_de_linhas` (percentual/seed,
    `ValidationError` vira mensagem em português + `sys.exit(1)`).
- [x] 9. Testes unit: fakes de cursor (`fetchmany`/`itersize`/
      `SSCursor`), streaming vs. não-streaming produzindo o mesmo
      `TabelaExtraida`, 0 linhas, lote parcial, exceção no meio do
      loop, `AmostragemPorFaixa` feliz/fallback/gaps/percentual
      inválido, `_elegibilidade_de_pk_para_faixa` isolada.
  - 0 linhas / lote parcial já cobertos no nível do helper
    (`ler_amostra_em_lotes`, item 5) — não duplicados no nível do
    Extrator.
  - `AmostragemPorFaixa` feliz/fallback/gaps/percentual inválido e
    `_elegibilidade_de_pk_para_faixa` isolada já cobertos nos itens 2/3.
  - Item novo: exceção no meio do `fetchmany` (Postgres e MariaDB) —
    prova que o `__exit__` do cursor de streaming roda com a exceção
    real antes dela propagar (não suprime, não deixa pendente), e que
    a conexão volta pro pool/fecha mesmo no caminho de erro.
- [x] 10. Testes de integração (`testcontainers`, Postgres 16 + MariaDB
       11 reais): `AmostragemPorFaixa` com PK íntegra vs. gap-heavy,
       streaming vs. não-streaming com mesma tabela sintética grande.
  - **Bug real encontrado e corrigido**: cursor nomeado do psycopg2 só
    popula `cursor.description` depois do 1º `fetchmany` (documentado no
    driver, não reproduzível com cursor mockado) — o streaming do
    Postgres estava lendo nomes de coluna vazios (`column_0`/`column_1`
    em vez de `id`/`nome`) antes do 1º fetch. `ler_amostra_em_lotes`
    deixou de receber `nomes_colunas` como parâmetro e passou a lê-los
    de `cursor.description` só depois de cada `fetchmany` — contrato
    novo, testado com fake simulando a mesma lacuna (unit) e provado
    contra Postgres real (integração).
  - Teste de gap-heavy (MariaDB) revisado: a 1ª tentativa (20 linhas
    concentradas no fim de um `AUTO_INCREMENT` alto) nunca dispararia o
    Aviso — `WHERE pk >= limiar ORDER BY pk LIMIT n` nunca devolve 0
    linhas enquanto `limiar <= MAX(pk)` (sempre existe pelo menos a
    própria linha de `MAX(pk)`), então o mínimo garantido (`K` faixas ×
    1 linha) só fica abaixo de `0.5 * n_pedido` com massa real grande o
    bastante (~1000 linhas) — não ~20. Desenho final: massa densa de
    999 linhas + 1 outlier isolado dominando `MAX(pk)`.
  - Equivalência streaming vs. não-streaming provada via
    `monkeypatch` do limiar de linhas pra 0 (não uma tabela realmente
    grande) — mesma tabela, mesmos ids, nos dois motores.
- **Bug real encontrado pelo usuário rodando contra produção** (pós-item
  11, antes do item 12): `pl.concat` em `ler_amostra_em_lotes` quebrava
  com `SchemaError: type Int64 is incompatible with expected type Null`
  numa tabela real (`public.token_acesso`) — cada lote do `fetchmany`
  infere seu próprio dtype por coluna, isolado dos outros; uma coluna
  nulável (`empresa_whitelabel_id`) cujo 1º lote saiu inteiro `NULL`
  infereu dtype `Null`, e o lote seguinte trazendo um valor `Int64` real
  pra essa mesma coluna quebrou o `concat` estrito. Não reproduzível com
  as tabelas sintéticas de teste (pequenas demais pra um lote inteiro
  sair 100% nulo por acidente). Corrigido com `pl.concat(lotes, how=
  "vertical_relaxed")` — funde pra um supertipo comum entre lotes
  (`Null` sempre funde com qualquer tipo). Teste unit novo reproduz o
  cenário isolado (lote 100% `NULL` seguido de lote com valor real).
- [x] 11. Benchmark (script versionado, reexecutável): tempo + RSS de
       pico antes/depois, incluindo amostra parcial (10%) sobre tabela
       outlier — calibra os limiares e `K` faixas ainda candidatos.
  - `test_extrator_postgres_benchmark_streaming.py` (marcado
    `benchmark`, não roda por padrão): mede tempo + RSS de pico em
    subprocessos isolados (`resource.getrusage` acumula por processo,
    não reseta entre chamadas) — (a) `PercentualDeLinhas` com/sem
    streaming forçado (`monkeypatch` do limiar), (b) `PercentualDeLinhas`
    vs. `AmostragemPorFaixa`, ambas sem streaming.
  - **Resultado real (1M linhas, ~150 bytes/linha, amostra ~100k
    linhas): redução de RSS de pico com streaming ficou em ~0%** — a
    baseline fixa de RSS de Python+psycopg2+polars (~185MB) domina
    nessa escala, mascarando o ganho. Achado honesto, não fabricado:
    o efeito só deve aparecer em escala próxima da real da issue
    (4,1M linhas/778MB, RSS ~900MB relatado) — calibração dos limiares
    finais fica para uma rodada manual do mesmo script numa tabela bem
    maior (fora do escopo de tempo desta sessão), não travada por isso.
  - `K` faixas do MariaDB: não recalibrado nesta rodada (só o lado
    Postgres foi medido, por ser o caso real que motivou a issue) —
    permanece candidato (`_K_FAIXAS = 10`).
  - **Confirmado contra produção real (pós-fix `vertical_relaxed`)**: o
    usuário rodou a extração completa contra o schema real (122
    tabelas, incluindo `token_acesso`) e RSS ficou baixo — validação
    prática do efeito que o benchmark sintético (1M linhas) não
    conseguiu mostrar por a baseline fixa do processo dominar naquela
    escala menor. Efeito real confirmado, mesmo sem número exato
    coletado (fora do escopo desta sessão instrumentar a extração real
    do usuário).
- [x] 12. Documentação: `docs/system_design_doc.md`,
       `docs/low_level_design.md` (novo membro da união, nova
       estratégia, streaming + limiares, limitação aceita de VACUUM
       represado), `plan/tasks.md` (reabertura de escopo Task 3).
  - `system_design_doc.md`: entrada de `AmostragemPorFaixa` na seção
    `EstrategiaDeAmostragem`, "Limitação de custo conhecida" reescopada
    só pra `PercentualDeLinhas`/`TabelaInteira`, nova subseção de
    streaming, `MetadadosDeAmostra.estrategia` atualizado.
  - `low_level_design.md`: união fechada com `RequisicaoPorFaixa`, nova
    seção `AmostragemPorFaixa` (padrão das duas anteriores + nota
    cruzada explicando por que reverte a escolha "sem viés"), dispatch
    de `RequisicaoPorFaixa` nos dois Extratores, e uma seção nova
    "Streaming via cursor server-side" cobrindo os dois bugs reais
    encontrados (description lazy do cursor nomeado; `pl.concat`
    estrito com coluna nula).
  - `plan/tasks.md`: reabertura de escopo na Task 3 (mesmo padrão de
    #44/#89/#95/#105), resumindo decisões técnicas + os 2 bugs reais.

## Correções pós-banca de revisão (pré-PR)

Antes de abrir o PR, a banca completa (arquiteto-de-software +
engenheiro-de-dados + po-revisor) revisou o diff final (`616e7a7...HEAD`)
em modo somente-leitura — mesma exigência da issue por mudança estrutural
cross-context. Plano de correção em
`/home/dev/.claude/plans/twinkly-churning-wilkinson.md`. Dois achados do
engenheiro de dados vieram com veredito **bloqueante**, ambos validados
empiricamente contra Postgres 16/MariaDB 11 reais; os dois foram corrigidos
antes do PR, junto com as ressalvas não-bloqueantes do arquiteto e do PO.

- [x] 1. **[BLOQUEANTE] MariaDB: `RAND(seed)` no `WHERE` é reavaliado por
      linha, não sorteia um corte fixo.** `RAND()` dentro de um `WHERE` do
      MariaDB é reavaliado a cada linha varrida pelo motor — a query nunca
      cortava a tabela num ponto aleatório fixo, e a amostra por faixa
      colapsava sistematicamente para os PKs mais baixos, para qualquer
      seed (validado via testcontainer + `EXPLAIN`: `type=index`, nem
      sequer usa seek de índice). O teste de integração existente só
      verificava `tamanho_amostra > 0`, nunca cobertura de PK — por isso
      não pegou o problema. Corrigido sorteando o corte de cada faixa em
      **Python** (`random.Random(seed_usado)`, um valor fixo por faixa),
      embutido como parâmetro literal — a query enviada ao MariaDB nunca
      mais tem `RAND()` no `WHERE`. Teste de integração estendido para
      checar cobertura por quartil de PK, não só `tamanho_amostra > 0`;
      passou contra MariaDB real.
- [x] 2. **[BLOQUEANTE] Postgres: `pg_stats.avg_width` mede tamanho
      comprimido (TOAST), não o tamanho real recebido pelo cliente.**
      Validado empiricamente: uma coluna `TEXT` de 50.000 bytes reais por
      linha (compressível) reportava `avg_width ≈ 585` — subestimativa de
      ~85x, gerando lotes de streaming superestimados exatamente nas
      tabelas mais largas que a issue existe para proteger. O benchmark
      original usava `TEXT` de alta entropia (baixa compressibilidade),
      por isso não expôs o problema. Corrigido com uma sonda física
      bounded: `_tabela_tem_coluna_toast_avel` identifica tabelas com
      coluna de tipo comprimível (`text`/`varchar`/`bpchar`/`json`/
      `jsonb`/`bytea`/`xml`); só para essas, `ExtratorPostgres.
      _largura_media_real` mede a largura via `octet_length(coluna::text)`
      sobre uma amostra `TABLESAMPLE SYSTEM` (mesmo mecanismo de
      `AmostragemPorFaixa`, custo O(amostra) não O(tabela)) — força a
      descompressão real. Tabelas sem coluna TOAST-ável continuam usando
      o `avg_width` de catálogo, sem round-trip extra. Teste de
      integração novo (Postgres real) confirma que a largura medida é
      >10x o valor de catálogo para uma coluna `TEXT` compressível.
- [x] 3. **[Ressalva forte, arquiteto] `MetadadosDeAmostra.estrategia`
      mentia no fallback do MariaDB.** No caminho de PK não elegível, o
      Extrator passava `nome=estrategia.nome` (`"amostragem_por_faixa"`,
      a escolha do wizard) em vez do mecanismo efetivamente usado
      (`AmostragemProbabilistica`) — um consumidor que só lê o artefato
      final (`contexto_de_ia.json`, markdown) via essa string, sem os
      `Aviso`s da extração, veria uma tabela marcada como lida por faixa
      quando na verdade foi varrida via `RAND() <= p`. Corrigido
      derivando o nome de `requisicao_efetiva` (o mesmo `match` já usado
      para `total_linhas_final`), não da `Estrategia` escolhida.
- [x] 4. **[Ressalva, engenheiro de dados] `vertical_relaxed` era um
      martelo mais amplo que o bug que corrigia.** `pl.concat(...,
      how="vertical_relaxed")` fundia silenciosamente qualquer par de
      dtypes divergentes entre lotes (ex. `Int64`↔`Utf8`), não só
      `Null`↔tipo-real — sem salvaguarda contra uma divergência
      genuinamente incompatível virar corrupção silenciosa de tipo.
      Corrigido com `_diverge_alem_de_null`: só aciona a fusão relaxada
      quando a única divergência entre lotes é `Null` vs. um tipo real;
      qualquer outra divergência usa `how="vertical"` (estrito) e deixa o
      erro propagar. Teste novo: dtypes genuinamente incompatíveis entre
      lotes propagam `SchemaError`, não fundem.
- [x] 5. **[Ressalva, PO] Streaming ativado não deixava rastro nenhum.**
      Apesar do risco documentado de represar `VACUUM`, nada indicava ao
      operador que o streaming tinha sido ativado para uma tabela.
      Corrigido com um log estruturado (`logging`, nível INFO) nos dois
      Extratores, emitido quando `usa_streaming=True` é decidido — cita
      tabela, linhas e bytes/linha estimados. Deliberadamente não virou
      campo em `MetadadosDeAmostra` (mecanismo de leitura é ortogonal à
      política de amostragem que esse Value Object descreve).
- [x] 6-7. **[Nice-to-have, arquiteto] Indireção decorativa e duplicação
      real não resolvida.** `_nomes_colunas` (Postgres, 1 call site, sem
      teste próprio) e o bloco inline equivalente do MariaDB duplicavam
      exatamente a lógica que `ler_amostra_em_lotes.py` já existia para
      compartilhar no caminho streaming. Extraído `ler_amostra_fetchall`
      como função irmã no mesmo módulo, reusada pelos dois Extratores no
      caminho não-streaming — remove a assimetria e ~15 linhas duplicadas
      de cada lado. `LARGURA_MEDIA_PADRAO_BYTES` (duplicada literalmente
      nos dois `_queries.py`) também migrou para `ler_amostra_em_lotes.py`,
      junto dos outros limiares da mesma decisão de streaming.

**Fora de escopo desta rodada (decisão explícita, registrada como
follow-up, não esquecimento):**

- Calibração formal dos limiares de streaming (100k linhas/100MB), `K=10`
  do MariaDB e `teto_bytes`/`minimo`/`maximo` do lote — o compromisso
  original ("calibrar por benchmark antes de fechar") ainda não foi
  cumprido; calibrar em cima da estimativa de largura que estava errada
  (achado 2) seria calibrar sobre dado incorreto. Fica para uma issue de
  follow-up, depois da correção do achado 2.
- Checar se a PK é efetivamente monotônica/`AUTO_INCREMENT` (não só tipo e
  cardinalidade) em `_elegibilidade_de_pk_para_faixa` — secundário ao
  achado 1, revisitar depois.
- Teste de carga concorrente de escrita validando o represamento de
  `VACUUM` — já era escopo removido no plano original (sem infraestrutura
  de workload de escrita simulado disponível).

## 2ª rodada de revisão (pós-correção, antes do PR)

Antes de abrir o PR, a banca completa revisou de novo o diff acumulado
(`git diff b75ecb9`, combinando os 2 commits dos itens 1-2 acima com o
restante ainda não commitado dos itens 3-7). Arquiteto e engenheiro de
dados confirmaram que os 2 achados bloqueantes da 1ª rodada foram
resolvidos de verdade (validado empiricamente contra bancos reais,
inclusive por reprodução independente do próprio engenheiro de dados).
Dois achados novos, ambos corrigidos antes do PR:

- [x] **[Bloqueante, engenheiro de dados] Detecção de coluna TOAST-ável
      (item 2) cobria só uma lista fixa de nomes de tipo** (`text`/
      `varchar`/`bpchar`/`json`/`jsonb`/`bytea`/`xml`), deixando escapar
      tipos comuns em produção que sofrem a mesma subestimativa: arrays
      (`udt_name` sempre prefixado com `_`, nunca bate contra a lista),
      `citext`, `hstore`, `tsvector` — validado empiricamente que uma
      coluna `text[]` de ~50KB reais reportava `avg_width ≈ 1073`
      (~47x subestimado), reintroduzindo o risco de pico de RSS pra
      exatamente esses tipos. Corrigido substituindo a lista fixa por uma
      query direta ao catálogo: `_COLUNAS_COMPRIMIVEIS_SCHEMA_SQL`
      (`pg_attribute.attstorage IN ('x', 'm')`, batched por schema, mesmo
      padrão das outras queries de `_MetadadosDoSchema`) — cobre qualquer
      tipo comprimível, incluindo arrays/domains/extensões, sem precisar
      listar cada um. Novo teste de integração (Postgres real) prova que
      uma tabela com coluna `TEXT[]` entra em
      `tabelas_com_coluna_comprimivel`, o que a detecção antiga não
      pegava.
- [x] **[Bloqueante, PO] Log de ativação de streaming (item 5) não era
      visível na prática** — nenhum ponto do código configurava
      `logging` (handler/nível), e o nível padrão do logger raiz do
      Python é `WARNING`; um `logger.info(...)` sem configuração é
      descartado antes de qualquer formatação. Os testes só "viam" a
      mensagem porque forçavam `caplog.at_level(INFO)` manualmente — o
      operador real do wizard não via nada. Corrigido com
      `_configurar_logging()` em `cli/wizard.py`, chamada no início de
      `executar()`: registra um `StreamHandler` pro logger `"ddf"` em
      nível INFO — agora o log de streaming (e também o log de exceção já
      existente em `pipeline/seguranca.py`, dormente pelo mesmo motivo)
      aparece no terminal por padrão. Teste novo confirma via `capsys`
      que a mensagem aparece de fato na saída, não só que o logger foi
      chamado.

Suíte completa (`mypy --strict src`, `ruff check .`, unit + integração
contra Postgres 16/MariaDB 11 reais) verde após as duas correções.

## 3ª rodada de revisão (confirmação pontual, antes do PR)

Banca focada nas duas correções da 2ª rodada, com escopo estreito. PO
confirmou o log resolvido (deixou de ser bloqueante); manteve como
recomendação não-bloqueante abrir uma issue real de calibração (2ª vez
que aparece só como texto no registry-plan, sem virar item rastreável no
tracker). Engenheiro de dados confirmou empiricamente (Postgres 16 real)
que `pg_attribute.attstorage IN ('x','m')` cobre os 4 casos que ele
apontou (array/citext/hstore/tsvector), mas achou um gap novo, também
corrigido antes do PR:

- [x] **[Sugestão, engenheiro de dados] `attstorage IN ('x','m')` excluía
      `'e'` (EXTERNAL)** — validado empiricamente que colunas com
      `STORAGE EXTERNAL` explícito (fora de linha, sem compressão) sofrem
      a mesma subestimativa, e pior: `avg_width` cai pro tamanho do
      ponteiro TOAST (~18 bytes), não um valor parcialmente comprimido.
      Caso raro (só via `ALTER TABLE ... SET STORAGE EXTERNAL`
      deliberado, nenhum tipo nativo usa por padrão), mas exatamente o
      tipo de coluna (grande, evitando overhead de compressão de
      propósito) que mais se beneficia da sonda. Corrigido trocando o
      filtro por `attstorage <> 'p'` — só `PLAIN` (largura fixa) nunca
      sai de linha, então é a única condição segura de excluir. Também
      adicionado `relkind IN ('r', 'p')` (mesmo padrão de
      `_TOTAL_LINHAS_SCHEMA_SQL` no mesmo arquivo) — não gerava falso
      positivo (Postgres não permite colisão de nome entre tabela e
      índice/view/sequence no mesmo schema), mas escaneava `pg_attribute`
      de relações irrelevantes à toa. Novo teste de integração
      (`test_deteccao_de_coluna_comprimivel_cobre_storage_external`)
      prova contra Postgres real.

Suíte completa verde após a correção; 57 testes de integração (subiu de
56), 543 unit.

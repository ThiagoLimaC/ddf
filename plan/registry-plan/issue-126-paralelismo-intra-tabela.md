# Issue #126 — paralelismo intra-tabela para leitura de tabelas grandes

Plano completo revisado em `/home/dev/.claude/plans/lexical-forging-scott.md`
(sessão de planejamento, 2026-08-10). Banca de revisão completa
(arquiteto-de-software + engenheiro-de-dados + po-revisor) rodada sobre o
plano antes da implementação — exigência do próprio critério já usado em
mudanças de risco/tamanho equivalente (#44/#89/#95/#105/#114). Veredito
inicial dos 3 revisores: **bloqueante**, 4 achados (validados contra os
mecanismos já em produção do projeto, não hipóteses soltas); todos
resolvidos no plano antes do código. Achados incorporados abaixo.

## Contexto

A extração hoje paraleliza **entre tabelas** (`OrquestradorParalelo`, uma
tabela por worker) — dentro de uma tabela, a leitura é sequencial (com
streaming via cursor desde a #114, mas um único cursor). Medição empírica
da própria issue #126 (Postgres 16 real, Docker: 20 tabelas pequenas + 1
outlier de 3M linhas/450MB, `TabelaInteira`) mostrou que o paralelismo
entre tabelas já extrai 100% do valor possível (+0,4% de diferença entre
"outlier isolada" e "outlier dentro do lote") — o gargalo é intrínseco à
leitura sequencial *daquela tabela*.

**Decisão de escopo fechada com o usuário:** implementar paralelismo
intra-tabela nos dois motores (Postgres e MariaDB) já nesta issue —
Postgres via `pg_export_snapshot()`/`SET TRANSACTION SNAPSHOT` (consistência
real entre conexões, mesmo mecanismo do `pg_dump --jobs`); MariaDB sem
equivalente leve (`FLUSH TABLES WITH READ LOCK` rejeitado, lock global),
aceitando e documentando risco de leitura inconsistente entre faixas
paralelas — mesma classe de trade-off já aceita pro viés de cluster de
`AmostragemPorFaixa` (#114).

## Achados bloqueantes da banca e resolução adotada

- **B1 (arquiteto) — deadlock real (hold-and-wait) no orçamento de
  conexões, não só contenção.** Reaproveitar o semáforo existente com
  aquisições independentes (líder adquire 1 permit, workers adquirem os
  seus depois) quebra o invariante "1 conexão por chamada de Extrator" que
  a #10 já contava como verdade — o líder fica bloqueado segurando seu
  permit enquanto espera os workers, que competem pelos permits restantes
  do mesmo semáforo; com várias tabelas grandes concorrentes, todos os
  permits podem ficar presos em líderes bloqueados. Resolução: reserva
  atômica de `max_conexoes_por_tabela` permits sob um `Lock` dedicado
  (`_reservar_conexoes`, `acquire(blocking=False)` em sequência, libera
  tudo e retorna `None` se qualquer uma falhar); sem reserva completa, `M`
  reduz progressivamente (mínimo 2) até cair no caminho sequencial — nunca
  bloqueia segurando permits parciais.
- **B2 (engenheiro de dados) — seed compartilhado entre faixas paralelas do
  MariaDB quebra independência estatística de `PercentualDeLinhas`.**
  `RAND(N)` do MariaDB reinicia a mesma sequência determinística a cada
  invocação com a mesma constante — o mesmo `seed_usado` literal em todas
  as M faixas faria a k-ésima linha de cada faixa herdar a mesma decisão
  de inclusão (correlação posicional nova, não existente na leitura
  sequencial atual). Resolução: cada worker usa `seed_usado +
  indice_da_faixa` como constante de `RAND(...)` — puramente interno ao
  `ExtratorMariaDB`, `MetadadosDeAmostra.seed` continua expondo só o seed
  canônico da tabela.
- **B3 (engenheiro de dados) — tabela particionada declarativamente
  (Postgres) quebra a premissa de `pg_relation_size(oid)`/`ctid` sobre a
  tabela-pai** (retorna 0/não mapeia fisicamente pra nada coerente).
  Resolução: detecção via `pg_partitioned_table` (query nova) populando
  `_MetadadosDoSchema.tabelas_particionadas`; tabela particionada nunca
  ativa paralelismo intra-tabela, cai no caminho sequencial/streaming já
  existente — degradação graciosa documentada, não erro. Suporte real a
  paralelismo particionado-aware fica fora de escopo.
- **B4 (po-revisor) — Aviso de risco por tabela no MariaDB reintroduz o
  ruído que a #116 já corrigiu** pro viés de cluster de `AmostragemPorFaixa`
  (mesmo texto estrutural repetido uma vez por tabela, não por execução).
  Resolução: `ExtratorMariaDB` guarda uma flag de instância protegida por
  lock e emite o Aviso só na primeira tabela que ativa paralelismo
  intra-tabela naquela execução — não dá pra mover pro wizard (como foi
  feito na #116) porque a ativação depende de tamanho real da tabela, só
  conhecido em runtime.

## Fase 0 — spike de validação técnica (bloqueia o resto, roda primeiro)

Pergunta em aberto que a investigação da #126 não resolveu: `TABLESAMPLE`
combinado com predicado `ctid` reduz blocos lidos no Postgres (via A), ou o
Sample Scan ignora o `ctid` como boundary de scan e cada worker acaba
varrendo a tabela inteira mesmo assim? `EXPLAIN (ANALYZE, BUFFERS)`
comparando com/sem filtro `ctid`, contra Postgres 16 real via
`testcontainers` — medições em sessões/containers isolados (evita cache de
buffer da 1ª query mascarar a 2ª), olhando `Buffers: shared read`
isoladamente. Não valida contenção de I/O físico concorrente entre M
workers reais (só o benchmark da Verificação cobre isso, parcialmente).

**Via B (se via A não confirmar):** ler cada partição `ctid` inteira (sem
`TABLESAMPLE` na query) e aplicar a decisão de inclusão em Polars, depois
de carregada — não piora o I/O físico (`PercentualDeLinhas`/`TabelaInteira`
já escaneiam a tabela inteira independente do percentual, limitação
conhecida da #56), mas aumenta volume transferido pela rede/driver. Só
compensa quando `percentual` já é alto — orientação do usuário: tratar
`percentual >= ~90` como equivalente, na prática, a `AmostragemIntegral`
pra fins de elegibilidade ao paralelismo intra-tabela.

### Resultado do spike (rodado — `test_spike_paralelismo_intra_tabela.py`)

Tabela sintética de 200k linhas/2858 blocos, faixa de 1/4 (714 blocos),
`EXPLAIN (ANALYZE, BUFFERS)`, cada medição contra tabela fisicamente
isolada (nunca tocada antes — 100% dos buffers vêm de `read`/primeira
leitura, sem contaminação de cache entre medições):

| Consulta | Blocos tocados (faixa/completa) | Plano |
|---|---|---|
| `ctid` puro, sem `TABLESAMPLE` (via B) | **0,25** (exato) | `Tid Range Scan`, `TID Cond: (ctid < ...)` |
| `TABLESAMPLE SYSTEM` + `ctid` (via A) | 0,91 | `Sample Scan` + `Filter: ctid < ...` — amostra a tabela inteira, filtra **depois** (`Rows Removed by Filter: 13790`) |
| `TABLESAMPLE BERNOULLI` + `ctid` (via A) | 0,99 | mesmo padrão, pior — `Rows Removed by Filter: 14956` |

**Via A descartada para as 3 Estrategias** — `TABLESAMPLE` (SYSTEM e
BERNOULLI) nunca usa `ctid` como boundary de scan no planejador do
Postgres 16; o predicado só filtra depois de amostrar a tabela inteira, o
que anularia qualquer ganho de paralelismo. **Via B confirmada e limpa** —
`ctid` puro aciona `Tid Range Scan`, blocos tocados escalam exatamente com
o tamanho da faixa.

**Decisão de escopo por Estrategia (final, com base no resultado real):**
- `AmostragemIntegral`: sempre elegível — via B é literalmente a query já
  usada por essa Estrategia (`SELECT * FROM tabela`), só com `ctid` como
  boundary de partição. Caso motivador do benchmark original da issue.
- `PercentualDeLinhas`/`AmostragemPorFaixa`: elegíveis só via B, e só
  quando `percentual >= ~90` (candidato, orientação do usuário) — ler a
  faixa `ctid` inteira e aplicar a decisão de inclusão (Bernoulli-
  equivalente) em Polars depois de carregada. Abaixo desse patamar, o
  custo de rede da via B não compensa — tabela segue sequencial no v1,
  registrado como reabertura de escopo futura (mesmo padrão de
  #56→#114→#116).
- **Nenhuma Estrategia usa `TABLESAMPLE` dentro do caminho paralelo** — a
  decisão de amostragem sempre acontece em Polars, depois da leitura física
  por `ctid`, nunca em SQL, quando o paralelismo intra-tabela está ativo.

## Decisões fechadas com o usuário (fora da banca)

- Escopo Postgres + MariaDB juntos nesta issue (não split), risco MariaDB
  aceito e documentado, não split em issue separada.
- Threshold `percentual >= ~90` para elegibilidade da via B — candidato,
  não calibrado.
- `max_conexoes_por_tabela` — parâmetro do construtor de cada Extrator
  (mesmo padrão de `max_conexoes`/`connect_timeout`), **não exposto no
  wizard da CLI**.

## Pausa — item 4a testado contra tabela real, ganho abaixo do esperado

Item 4a (`AmostragemIntegral` paralela no Postgres) testado contra uma
tabela real de ~4M linhas: ganho de só ~15-20% de tempo de parede (55-58s
vs. 65-70s sequencial), bem abaixo do esperado. Duas revisões
(arquiteto-de-software + engenheiro-de-dados) confirmaram, com medição
empírica, que o gargalo dominante é o **GIL do Python** na
decodificação/construção do `pl.DataFrame` a partir de tuplas — medido
1.24x de ganho com 4 threads (teto teórico 4x), threads essencialmente
serializadas. Teto estrutural do desenho `ThreadPoolExecutor`+`psycopg2`,
herdado por qualquer extensão dele (itens 4b/5/8).

**Decisão do usuário:** pausar a #126 nesse ponto (itens 4b, 5-9 abaixo
ficam em espera) e mapear antes se uma biblioteca Rust que decodifica
direto pra Arrow/Polars sem passar por objetos Python resolve o problema
de raiz. Mapeamento de escopo (`connectorx` vs. ADBC) feito e aprovado —
ver plano de sessão arquivado; recomendação: `connectorx` em modo de
particionamento manual sobre `ctid`, sujeito a um spike de validação
antes de qualquer decisão de arquitetura.

### Spike de validação (`connectorx`) — rodado contra Postgres 16 e MariaDB 11 reais

Arquivos: `tests/integration/extractors/postgres/test_spike_connectorx.py`
e `tests/integration/extractors/mariadb/test_spike_connectorx.py`, ambos
marcados `benchmark`, com `pytest.importorskip("connectorx")` (lib não é
dependência do projeto — só instalada no ambiente do spike). Performance
medida à parte, contra o dump real do usuário (`token_acesso`, 4.1M
linhas, 690MB — a mesma tabela do teste original de #126), via script
standalone fora da suíte.

1. **Performance real**: 4 partições `ctid` via `connectorx`: 9.33s vs.
   25.53s sequencial (`psycopg2`/`fetchall`) — **2.7x**. 8 partições:
   6.45s — **quase 4x**. Contra o ~1.2x do `ThreadPoolExecutor`+`psycopg2`,
   confirma que o GIL era mesmo o gargalo estrutural, não I/O de disco.
   Achado colateral: 1 partição via `connectorx` foi mais lenta que o
   sequencial (58s) — overhead de conexão só se paga com paralelismo real,
   não é um substituto de leitura sequencial de partição única.
2. **`SET TRANSACTION SNAPSHOT`**: funciona, mas não do jeito documentado.
   Precisa de `pre_execution_query=["BEGIN ISOLATION LEVEL REPEATABLE
   READ", "SET TRANSACTION SNAPSHOT '<id>'"]` (a ordem importa — sem o
   `BEGIN` explícito, falha com "must have isolation level SERIALIZABLE or
   REPEATABLE READ"). Confirmado empiricamente que a partição não vê linha
   inserida após o export do snapshot. Risco 1 do mapeamento de escopo:
   mitigável (não documentado pela lib, mas funcional).
3. **`NUMERIC` sem precisão/escala fixa**: pior que o risco documentado —
   não trunca silenciosamente, **crasha** (`RuntimeError: decimal scale is
   not equal to expected scale, got: 9 expected: 10`) assim que duas linhas
   do resultado têm escalas decimais diferentes. Qualquer tabela de
   produção com `NUMERIC` de escala variável quebraria a extração inteira,
   não silenciosamente — precisaria de tratamento explícito (cast
   controlado ou exclusão da via paralela) antes de qualquer adoção.
4. **`ENUM`/`SET` do MariaDB**: fidelidade confirmada contra MariaDB 11
   real — chegam como string, idêntico ao que `pymysql` já lê hoje. Risco
   de tipo mitigado. Não resolve (nem piora) a lacuna pré-existente de
   consistência entre faixas no MariaDB (sem `pg_export_snapshot`
   equivalente) — independente da lib de leitura escolhida, continua risco
   aceito e documentado.
5. **`mypy --strict`**: `connectorx` publica `py.typed` + stub `.pyi` —
   checagem limpa contra uso real, sem `# type: ignore`.

**Conclusão do spike**: os dois riscos que o mapeamento de escopo não
conseguia resolver só com documentação (consistência de snapshot,
`NUMERIC`) têm caminho de contorno real — snapshot funciona (modo não
documentado), `NUMERIC` crasha de forma detectável (não corrompe dado
silenciosamente) e é tratável com validação explícita antes da leitura.
Combinado ao ganho de performance confirmado (2.7-4x vs. ~1.2x), o balanço
pende para viabilidade técnica.

**Decisão do usuário (2026-08-10): refatorar a #126** (não abrir issue
nova) — issue já atualizada no GitHub (título + corpo refletem o pivô pra
`connectorx`). Camada de particionamento/política reaproveitada como
estava (`particoes_de_blocos`, detecção de tabela particionada,
`deve_paralelizar_leitura`/`reservar_conexoes`/`liberar_conexoes`); camada
de execução física do item 4a (Postgres) reescrita — ver seção seguinte.

## Item 4a reescrito para `connectorx` (substitui `ThreadPoolExecutor`+`psycopg2`)

`ExtratorPostgres._ler_tabela_em_paralelo` não abre mais uma conexão por
faixa via `ThreadPoolExecutor`/`_conexao_ja_reservada` — a conexão líder
segue exportando o snapshot e mantendo a transação `REPEATABLE READ`
aberta (mecanismo inalterado), mas as `n` faixas de `ctid` viram uma lista
de strings SQL (`_query_particao_ctid`, renderizada via
`sql.Composed.as_string`) entregues numa única chamada a
`cx.read_sql(dsn, queries, return_type="polars", pre_execution_query=[...])`
— o `connectorx` abre e gerencia as próprias conexões (fora do
`ThreadedConnectionPool` deste Extrator) e decodifica pra Arrow/Polars fora
do GIL. `_ler_particao_em_conexao`/`_ler_particao_com_snapshot` (cursor
Python por faixa) e `concatenar_particoes` (merge manual das faixas) foram
removidos — código morto depois da troca; `connectorx` já devolve um único
`pl.DataFrame` concatenado. Falha do `connectorx` (ex.: o crash conhecido
de `NUMERIC` sem escala fixa, achado 3 do spike) vira `Falha`, não exceção
não tratada.

Validado contra o mesmo Postgres 16 sintético dos testes de integração já
existentes (`test_extrator_postgres_paralelismo_intra_tabela.py` — nenhuma
mudança precisou ser feita neles, corretude confirmada sem alteração) e,
manualmente, contra o dump real do usuário (`token_acesso`, 4.1M linhas):
lote completo de 122 tabelas caiu de ~53-58s pra **11-12s** depois dos dois
achados colaterais abaixo serem corrigidos.

**Achados colaterais, corrigidos na mesma sessão:**
- **Folga de conexões insuficiente entre `OrquestradorParalelo` e
  `ExtratorPostgres`.** `max_conexoes` do Extrator (default 8) e
  `max_trabalhadores` do Orquestrador (default 8, hardcoded no wizard)
  competem pelo mesmo orçamento de conexões do Postgres — sob carga
  concorrente real (todas as 122 tabelas do lote), as 8 conexões já
  estavam em uso por outras tabelas no instante em que `token_acesso`
  tentava reservar as suas, e `reservar_conexoes` nunca achava as 2
  mínimas livres (fallback silencioso pro caminho sequencial, sem erro,
  mas paralelismo intra-tabela nunca ativando de verdade). Corrigido em
  `cli/registro/extratores.py` (`_MAX_CONEXOES_POSTGRES = 12`, +4 de folga
  sobre os 8 trabalhadores do Orquestrador) — só no wizard, não no
  `ExtratorPostgres` em si (bounded context do Extrator não conhece o
  Orquestrador).
- **Log de particionamento em nível errado.** `_logger.warning("dividindo
  em N faixas...")` vazava no meio da barra de progresso do wizard mesmo
  sem nenhum logging configurado — `logging.lastResort` do Python imprime
  `WARNING`+ no stderr por padrão, mesmo sem handler. Rebaixado pra `INFO`
  (mesmo nível das outras duas linhas de log do método; a mensagem é
  informativa, não um problema ocorrendo) — resolve o vazamento sem
  precisar bufferizar log durante a barra de progresso.
- Uma tentativa de ligar `_configurar_logging()` (função já existente,
  testada, mas nunca chamada por `executar()`) foi revertida — o log em
  `INFO` interrompia o redesenho por cursor relativo da barra de progresso
  (`prompts.progresso_paralelo`/`_desenhar`, `cli/prompts.py:394-407`),
  imprimindo "Tabelas extraídas" duplicado. Ligar essa função de verdade
  exige bufferizar o log durante a Etapa 4 e exibir só depois da barra
  terminar — fora de escopo desta sessão, registrado como possível
  reabertura futura.

## Checklist de execução

- [x] 0. Este arquivo (registry-plan).
- [x] 1. Spike Fase 0 (`tests/integration/extractors/postgres/
      test_spike_paralelismo_intra_tabela.py`, marcado `benchmark`) — via A
      descartada (TABLESAMPLE ignora `ctid` como boundary, filtra depois);
      via B confirmada (`Tid Range Scan`, blocos escalam exatamente com o
      tamanho da faixa). Resultado registrado acima.
- [x] 2. `extractors/comum/leitura_paralela_intra_tabela.py` —
      `deve_paralelizar_leitura` (limiares candidatos: 500.000 linhas /
      500MB, não calibrados); `reservar_conexoes`/`liberar_conexoes`
      (reserva atômica sob `Lock` dedicado — resolve o achado B1 do
      arquiteto: serializa tentativas de reserva, nunca deixa uma thread
      de posse parcial de permits esperando pelo resto; reduz
      progressivamente até `MINIMO_CONEXOES_PARALELISMO=2`, retorna `0` se
      nem isso estiver disponível). Testes unitários
      (`test_leitura_paralela_intra_tabela.py`, 12 casos feliz/borda/erro,
      incluindo reserva concorrente de 10 threads sobre um semáforo de
      capacidade 8 nunca excedendo o total) + `mypy --strict`/`ruff`
      limpos.
- [x] 3. `extractors/comum/ler_amostra_em_lotes.py` — extraída
      `concatenar_particoes` (reuso real: `ler_amostra_em_lotes` passou a
      chamá-la pro merge de lotes existente; merge de partições da leitura
      paralela intra-tabela reaproveita a mesma função). 4 testes novos
      (feliz/borda×2/erro) + os 10 já existentes continuam verdes.
      `mypy --strict`/`ruff` limpos no projeto inteiro (95 arquivos), 582
      testes unitários passando.
- [x] 4a. `ExtratorPostgres` — paralelismo intra-tabela pra
      `AmostragemIntegral` (escopo fatiado com o usuário: `PercentualDeLinhas`/
      `AmostragemPorFaixa` com `percentual >= ~90%` via filtro em Polars
      vira item **4b**, ainda não implementado). **Implementação original
      abaixo (`ThreadPoolExecutor`+`psycopg2`) substituída por `connectorx`
      — ver "Item 4a reescrito para connectorx" acima; detalhes de
      particionamento/snapshot/detecção de tabela particionada continuam
      válidos, só a camada de execução física mudou:**
      - `max_conexoes_por_tabela: int | None = None` no `__init__`,
        default `min(4, max_conexoes)` (nunca levanta `ValueError` por
        conta própria — só quando explicitado incompatível); validação
        ajustada durante a implementação: `<=` (não `<`) `max_conexoes`,
        já que consumir o orçamento inteiro numa tabela é uma escolha
        válida, não um erro.
      - Detecção de tabela particionada via `pg_class.relkind = 'p'`
        (`_TABELAS_PARTICIONADAS_SCHEMA_SQL`) — mais simples que
        `pg_partitioned_table`, mesmo padrão de catálogo já usado no
        arquivo. Tabela particionada nunca ativa paralelismo, cai no
        sequencial sem erro (testado).
      - `reservar_conexoes`/`liberar_conexoes` em volta de
        `_ler_tabela_em_paralelo`; conexão líder exporta snapshot
        (`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ` +
        `SELECT pg_export_snapshot()`) e lê sua própria faixa (não é só
        coordenadora) — workers importam via `SET TRANSACTION SNAPSHOT`,
        cada um commitando assim que termina; líder só commita depois que
        todos terminam (`ThreadPoolExecutor` dedicado, nunca o do
        Orquestrador). Partição via `particoes_de_blocos` (`ctid`, última
        faixa aberta) + `_TOTAL_BLOCOS_TABELA_SQL`.
      - **Bug real encontrado e corrigido pelo teste de integração, não
        pego por nenhum teste unitário mockado:** `format('%I.%I', ...)`
        na query de blocos colidia com a substituição `%s` do psycopg2
        (`%I` sendo consumido como parâmetro) — corrigido escapando
        `%%I`. Só reproduzível contra Postgres real.
      - Testes: unitários de `particoes_de_blocos` (7 casos) +
        construtor/elegibilidade de `ExtratorPostgres` (5 casos novos) +
        2 testes de integração via `testcontainers` (corretude: paralelo
        vs. sequencial produz o mesmo conjunto de `id`s, sem overlap; e
        confirmação de que o caminho paralelo foi de fato exercitado, via
        log). Suíte completa: `ruff`/`mypy --strict` limpos, 593 testes
        unitários + 31 de integração Postgres verdes.
- [x] 5. `ExtratorMariaDB` — paralelismo intra-tabela pra `AmostragemIntegral`
      (mesmo escopo fatiado do item 4a: `PercentualDeLinhas`/
      `AmostragemPorFaixa` continuam fora, viram 4b junto do Postgres).
      **Já nasceu via `connectorx`, direto — nunca existiu uma versão
      `ThreadPoolExecutor` deste item** (item 5 só foi implementado depois
      do pivô, diferente do 4a que foi reescrito):
      - `max_conexoes_por_tabela` no `__init__` (mesma validação do
        `ExtratorPostgres`); `_conexao()` passou a usar `self._semaforo`
        (antes só dependia do `blocking=True` do `PooledDB`) — necessário
        pra contar as conexões que o `connectorx` abre por conta própria
        (fora do `PooledDB`) contra o mesmo orçamento `max_conexoes`.
      - Sem conexão líder nem snapshot (MariaDB não tem equivalente) —
        `particionar_faixas_exaustivas` (`mariadb/_construcao.py`, mesmo
        algoritmo de `particoes_de_blocos`, aplicado a domínio de PK via
        `MIN`/`MAX` em vez de bloco físico) gera as faixas; elegibilidade
        reaproveita `_elegibilidade_de_pk_para_faixa` (já existia pra
        `RequisicaoPorFaixa` — PK de coluna única e tipo inteiro).
      - Aviso de risco de consistência entre faixas emitido uma única vez
        por execução (flag de instância + lock, resolve o mesmo tipo de
        ruído do achado B4).
      - Sem detecção de tabela particionada nativa do MariaDB (diferente
        do Postgres) — fora do escopo desta rodada, candidato futuro.
      - Testes: 15 unitários de `particionar_faixas_exaustivas`
        (feliz/borda/erro) + 2 de integração via `testcontainers` contra
        MariaDB 11 real (corretude sem overlap/gap; confirmação de
        ativação + Aviso). Suíte completa: `ruff`/`mypy --strict` limpos,
        662 testes unitários passando.
- [x] 6. Testes unitários de partição (feliz/erro/borda) cobertos nos
      itens 4a/5 acima, um conjunto por motor (`particoes_de_blocos`
      Postgres, `particionar_faixas_exaustivas` MariaDB); `reservar_conexoes`/
      `liberar_conexoes` já cobertos no item 2 (motor-agnóstico, reusado
      por ambos).
- [x] 7. Testes de integração de corretude via `testcontainers` (Postgres
      16 + MariaDB 11 reais) — `AmostragemIntegral` por conjunto idêntico
      de `id`s, sem overlap/gap, nos dois motores (itens 4a/5). Escopo
      restrito à `AmostragemIntegral`: `PercentualDeLinhas`/
      `AmostragemPorFaixa` (item 4b) e tabela particionada Postgres cair
      no sequencial sem erro já tinham cobertura própria antes deste
      pivô, não precisaram de teste novo.
- [ ] 8. Benchmark versionado (marcado `benchmark`, mesmo padrão da #114)
      reproduzindo o cenário da issue (tabela grande sintética) — resultado
      sujeito à mesma ressalva de Docker local vs. produção já registrada
      na investigação original.
- [x] 9. `docs/system_design_doc.md` (Decisão de arquitetura 14) +
      `docs/low_level_design.md` (nova seção "Paralelismo intra-tabela via
      connectorx", logo depois de "Streaming via cursor server-side") +
      `plan/tasks.md` (nova entrada na seção 3).
- [x] 10. Banca de revisão multi-agente pós-implementação (2026-08-11):
      arquiteto-de-software + engenheiro-de-dados + po-revisor, rodando em
      modo auto contra `git diff development...HEAD` (22 arquivos, ~1942
      inserções). Veredito inicial: bloqueante (2 de 3 revisores vetaram
      merge). 6 achados corrigidos, plano em
      `/home/dev/.claude/plans/lexical-forging-scott.md`:
      - **[Bloqueante] Wizard sem folga de `max_conexoes` no MariaDB**
        (arquiteto + po-revisor) — `_construir_extrator_mariadb` não
        passava a mesma folga que `_construir_extrator_postgres` já
        aplicava sobre o `max_trabalhadores` do `OrquestradorParalelo`; o
        paralelismo intra-tabela do MariaDB nunca ativava de verdade via
        wizard. Corrigido com `_MAX_CONEXOES_MARIADB = 12`
        (`cli/registro/extratores.py`).
      - **[Bloqueante] Risco de self-deadlock na sonda `MIN`/`MAX` do
        MariaDB** (engenheiro-de-dados) — `_ler_tabela_em_paralelo`
        reabria o semáforo via `self._conexao()` depois que
        `reservar_conexoes` já tinha tomado os permits disponíveis, sem
        timeout em nenhum `acquire`. Corrigido extraindo a sonda pra
        `_dominio_de_pk`, chamada antes da reserva.
      - **[Bloqueante] Orçamento de conexões do Postgres não batia com o
        documentado** (engenheiro-de-dados) — a conexão líder
        (`pg_export_snapshot`) consumia 1 conexão real além das `n`
        reservadas. Corrigido particionando em `n - 1` faixas.
      - **[Bloqueante] Crash do connectorx (ex.: `NUMERIC`) derrubava a
        tabela inteira** (po-revisor + engenheiro-de-dados, achado
        convergente) — regressão em relação ao caminho sequencial, que
        sempre soube ler essa mesma tabela. Corrigido com fallback pro
        sequencial + `Aviso` legível (nos dois motores).
      - **[Importante] `connect_timeout` não chegava às conexões do
        connectorx** (arquiteto) — corrigido no Postgres (DSN dedicada,
        `self._dsn_connectorx`); testado empiricamente que o driver MySQL
        do connectorx rejeita esse parâmetro em qualquer variação de nome
        (`connect_timeout`, `connect-timeout`, `timeout`,
        `connectTimeout` — todos `RuntimeError: Unknown URL parameter`),
        risco aceito e documentado no MariaDB.
      - **[Importante] Nenhum teste provava que o snapshot do Postgres
        protegia contra escrita concorrente** (engenheiro-de-dados) —
        novo teste de integração
        (`test_leitura_paralela_preserva_consistencia_sob_escrita_concorrente`)
        com uma thread escrevendo sem parar durante toda a extração
        paralela; assertion é "todas as faixas veem a mesma versão", não
        uma versão específica, já que o timing exato entre
        `pg_export_snapshot` e os commits concorrentes não é controlável
        pelo teste. Estável em 3 execuções consecutivas.
      - Sugestões da banca **não implementadas** (não bloqueiam,
        candidatas a follow-up): duplicação genuína entre
        `particionar_faixas_exaustivas`/`particoes_de_blocos`; unificação
        `_conexao`/`_conexao_ja_reservada`; detecção prévia de `NUMERIC`
        sem escala fixa antes de tentar o caminho paralelo (o fallback do
        item acima já evita a regressão, só não evita a tentativa);
        convenção de docstring `TestErro`; opt-out de CLI pro paralelismo
        automático; texto do `Aviso` do MariaDB mais concreto pra
        não-DBA.
      - 665 testes (unit + integração real Postgres 16/MariaDB 11) verdes
        ao final, `mypy --strict`/`ruff` limpos.

## Fora de escopo

- Otimização de queries de catálogo (`information_schema` → `pg_catalog`) e
  `statement_timeout`/`lock_timeout` — já fora de escopo na issue #126
  original.
- Calibração final dos limiares (`deve_paralelizar_leitura`,
  `max_conexoes_por_tabela` default, `percentual >= ~90`) — candidatos
  iniciais, mesmo tratamento dos limiares de streaming da #114.
- Teste de carga concorrente de escrita durante extração paralela — coberto
  pra Postgres no item 10 (achado da banca); MariaDB continua sem teste
  equivalente porque o próprio design não tem garantia de consistência a
  provar (risco já aceito e comunicado via `Aviso`, não faria sentido
  testar ausência de uma garantia que nunca existiu).
- Paralelismo particionado-aware sobre tabela particionada Postgres (1
  worker por partição física) — só detecção + fallback gracioso entram no
  v1.

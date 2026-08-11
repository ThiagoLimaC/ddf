# Tarefas


## 1. Setup do ambiente de desenvolvimento

- [ ] `uv init`, `pyproject.toml` com Python 3.12+ e as dependências base
      (pydantic, psycopg2-binary, polars, jinja2, pyyaml, click, questionary)
- [ ] Estrutura de pastas:
        `src/ddf/domain/{model,ports,shared}`,
        `src/ddf/pipeline/`,
        `src/ddf/infrastructure/adapters/{extractors,analyzers,generators,orchestrator,overrides,cli}`,
        `tests/unit/...`,
        `tests/integration/...`
- [ ] `ruff` com `select = ["E","F","W","I","N","D"]` e
      `pydocstyle convention = "google"`
- [ ] `mypy --strict`
- [ ] Workflow de CI (GitHub Actions) rodando `ruff` + `mypy` + `pytest` a cada
      push

## 2. Modelo de domínio

### Shared (`domain/shared/`)

- [x] `Aviso` (dataclass frozen) — `mensagem: str`, `origem: str`
- [x] `Resultado[T]` como sum type — `Sucesso[T](valor, avisos: list[Aviso])` |
      `Falha(erro: str)`

### Modelos compartilhados (`domain/model/common`)

- [x] `TipoDeDado` — `CategoriaDeDado` (Enum) +
      `precisao`/`escala`/`tamanho_maximo` opcionais
- [x] `MetadadosDeAmostra` — `estrategia: str`, `tamanho_amostra: int`,
      `total_linhas: int`
- [x] `ConfiguracaoDeExtracao` — `estrategia: EstrategiaDeAmostragem`
      (reabertura de escopo da issue #10: `max_trabalhadores`/`max_conexoes`
      removidos — nunca foram uma distinção com diferença real; concorrência
      segura é responsabilidade interna e encapsulada de cada `Extrator`
      concreto, ver `plan/registry-plan/issue-10-*.md`)

### Extraction Context (`domain/model/extraction.py`)

- [x] `ColunaExtraida` — `nome`, `tipo_dado`, `chave_primaria`,
      `chave_estrangeira`, `referencia: ReferenciaDeColuna | None`
- [x] `TabelaExtraida` — `nome_tabela`, `nome_escopo`,
      `colunas: list[ColunaExtraida]`, `total_linhas`,
      `amostra: pl.DataFrame | None`, `metadados_amostra`;
      `arbitrary_types_allowed=True`

### Curation Context (`domain/model/curation.py`)

- [x] `ColunaCurada` — `ColunaExtraida` + `papel_de_negocio`,
      `regras_de_negocio`
- [x] `TabelaCurada` — mesma estrutura de `TabelaExtraida` com `ColunaCurada` +
      `papel_de_negocio`, `regras_de_negocio`; `arbitrary_types_allowed=True`
- [x] `BancoCurado` — `tabelas: list[TabelaCurada]`;
      `arbitrary_types_allowed=True`

### Analysis Context (`domain/model/analysis.py`)

- [x] `MetricaDeColuna` (BaseModel frozen) — `origem: str` — Value Object base
- [x] `MetricasBaseColuna(MetricaDeColuna)` — `percentual_nulo`, `percentual_unico`,
      `valores_frequentes`, `minimo`, `maximo`, `formato_detectado`;
      `origem = "AnalisadorDeMetricasDeColuna"`
- [x] `MetricaDeTabela` (BaseModel frozen) — `origem: str` — Value Object base
- [x] `MetricasBaseTabela(MetricaDeTabela)` — `completude: float`;
      `origem = "AnalisadorDeMetricasDeTabela"`
- [x] `ColunaAnalisada` — campos de `ColunaCurada` +
      `metricas: list[MetricaDeColuna]`
- [x] `TabelaAnalisada` — campos de `TabelaCurada` (sem amostra) +
      `metricas: list[MetricaDeTabela]` + `metadados_amostra`
- [x] `BancoAnalisado` — `tabelas: list[TabelaAnalisada]`; Pydantic puro
- [x] `ContextoDeAnalise` — `curado: BancoCurado`, `analisado: BancoAnalisado`;
      `arbitrary_types_allowed=True`
- [x] `iniciar_contexto(curado: BancoCurado) -> ContextoDeAnalise` —
      constrói `BancoAnalisado` vazio a partir de `BancoCurado`

### Pipeline (`pipeline/`)

- [x] `Estagio[Entrada, Saida]` (Protocol genérico) em `pipeline/estagio.py`
- [x] `compor(*estagios)` em `pipeline/compor.py` — acumula avisos, para no
      primeiro `Falha`

### Ports (`domain/ports/`)

- [x] `Extrator` (Protocol) — `listar_escopos() -> Resultado[list[str]]`,
      `listar_tabelas(escopo) -> Resultado[list[tuple]]`,
      `extrair_tabela(escopo, tabela) -> Resultado[TabelaExtraida]`
      (issue #34: `listar_escopos` adicionado, vocabulário generalizado de `schema` para `escopo`)
- [x] `Analisador` (Protocol) — `produz`, `requer`,
      `__call__(ContextoDeAnalise, /) -> Resultado[ContextoDeAnalise]`
      (parâmetro positional-only desde a revisão pré-CLI, issue #53)
- [x] `Gerador` (Protocol) — `requer`,
      `__call__(BancoAnalisado, destino, /) -> Resultado[None]`
      (parâmetro positional-only desde a revisão pré-CLI, issue #53)
- [x] `OrquestradorDeTabelas` (Protocol) — `extrair(escopos, extrator) ->
      Resultado[list[TabelaExtraida]]` + `aplicar_sobrescritas(tabelas, sobrescrita)
      -> Resultado[BancoCurado]`
- [x] `EstrategiaDeAmostragem` (Protocol) — `nome: str`, `percentual: float`
      (política pura, sem SQL — cada Extrator traduz pro próprio dialeto)

### Contrato da CLI (`infrastructure/adapters/cli/`)

- [x] `EXTRATORES_REGISTRADOS` + `registrar_extrator()` (renomeado de
      `FONTES_REGISTRADAS`/`registrar_fonte()` na issue #16, junto de
      `cli/fontes.py` → `cli/registro/extratores.py`) — registro de
      Extratores disponíveis; define o contrato de extensão desde o início
- [x] `wizard.py` — implementado por completo na Task 7/issue #16 (ver
      seção 7 abaixo)
- [x] `validar_dependencias(analisadores, geradores) -> Resultado[None]` em
      `cli/validacao.py` — lógica pura, testável sem adapters concretos

- [x] **Verificação:** testes de validação Pydantic (`percentual_nulo`/
      `percentual_unico`/`completude` entre 0–100 em
      `MetricasBaseColuna`/`MetricasBaseTabela`). A validação de
      `max_conexoes >= max_trabalhadores` em `ConfiguracaoDeExtracao` citada
      na v1 desta task não existe mais — reaberta e removida na issue #10 (ver
      nota acima em "Modelos compartilhados").

## 3. Adaptador de Extrator concreto

- [x] `domain/model/common/tipo_de_dado.py` — reabertura de escopo da #5:
  novas categorias `FLOAT`, `CHAR`, `UUID`, `TIME`; novos atributos
  `tamanho_fixo` (CHAR) e `com_timezone` (TIMESTAMP e TIME) em `TipoDeDado`;
  `_ATRIBUTOS_PERMITIDOS` atualizado; testes novos em `test_tipo_de_dado.py`
- [x] `domain/ports/estrategia_de_amostragem.py` — reabertura de escopo da #8:
  `consulta()` removido do Port; vira política pura (`nome`, `percentual`),
  sem gerar SQL — cada Extrator traduz pro próprio dialeto
- [x] `PercentualDeLinhas(EstrategiaDeAmostragem)` — só guarda `percentual`
  (0, 100]; substitui `LimiteAleatorio` (descartada: LIMIT absoluto não
  escala entre tabelas de tamanhos muito diferentes)
- [x] `ExtratorPostgres(Extrator)`:
  - Pool preguiçoso: `__init__` só guarda `dsn`/`configuracao`, sem revalidar
    `max_conexoes >= max_trabalhadores` (já garantido por `ConfiguracaoDeExtracao`);
    `ThreadedConnectionPool` só é criado no 1º uso — corrige bug encontrado
    durante os testes (o pool conecta de verdade no `__init__`, então DSN
    inválido levantava exceção crua em vez de `Falha`)
  - `listar_tabelas` via `information_schema.tables`
  - `extrair_tabela` — lê estrutura (colunas + PK via `table_constraints`/
    `key_column_usage` + FK via `constraint_column_usage`) + `total_linhas`
    via `pg_catalog.pg_class.reltuples` (estimativa) + amostra via
    `TABLESAMPLE BERNOULLI(configuracao.estrategia.percentual)` (sem viés
    posicional, ao contrário de LIMIT sem ORDER BY) + carrega `pl.DataFrame`
    + `tamanho_amostra = len(dataframe)` + constrói `TabelaExtraida`
  - Mapeamento completo tipos Postgres → `TipoDeDado` (ver tabela em
    `docs/low_level_design.md`)
- [x] `conftest.py` de `tests/unit/infrastructure/adapters/extractors/` e
      `extractors/postgres/` — `PercentualDeLinhas`, `mapear_tipo_postgres` e
      `ExtratorPostgres` (construção preguiçosa, `listar_tabelas`,
      `extrair_tabela`) cobertos feliz/erro/borda
- [x] Teste de integração em `tests/integration/extractors/postgres/` via
      `testcontainers` (Postgres 16 real, descartável por sessão de teste):
      `listar_tabelas` (feliz/borda) e `extrair_tabela` (feliz completo incl.
      `TIMESTAMP com_timezone`, erro escopo/tabela inexistente, erro DSN
      inválido)
- [x] `testcontainers[postgres]` adicionado ao grupo dev do `pyproject.toml`
      (junto de `types-psycopg2`, necessário pra `mypy --strict` reconhecer
      os tipos do `psycopg2`)
- [x] `domain/model/common/tipo_de_dado.py` — reabertura de escopo da #35:
      novas categorias `ENUM`/`SET`, atributo `valores_permitidos` (partilhado
      entre as duas); testes novos em `test_tipo_de_dado.py`
- [x] `ExtratorMariaDB(Extrator)` — segunda fonte relacional real (issue #35),
      prova de Open/Closed e de que `nome_escopo: str` flat (generalização da
      #34) aguenta o colapso schema/database do MariaDB sem precisar virar
      Value Object hierárquico:
  - Pool preguiçoso via `dbutils.pooled_db.PooledDB` (mesmo padrão do
    Postgres), sem semáforo manual (`PooledDB(blocking=True)` já serializa
    chamadas concorrentes quando o pool está esgotado)
  - `listar_escopos`/`listar_tabelas` via `information_schema.schemata`/
    `.tables`; PK/FK num único ponto de leitura
    (`information_schema.key_column_usage`, que já traz schema/tabela/coluna
    referenciados direto, sem JOIN extra como o Postgres precisa)
  - `total_linhas` via `information_schema.tables.TABLE_ROWS`; amostra via
    `WHERE RAND() <= percentual/100` (MariaDB não tem `TABLESAMPLE`)
  - `tinyint` sempre mapeia INTEGER em `mapear_tipo_mariadb` (função pura);
    promoção INTEGER→BOOLEAN é feita à parte por `ExtratorMariaDB`, com base
    nos valores reais da amostra já buscada (nunca por convenção de nome de
    coluna) — MariaDB não guarda em lugar nenhum a distinção BOOLEAN vs
    TINYINT(1)
  - `ENUM`/`SET` mapeados com `valores_permitidos` parseado de `COLUMN_TYPE`
- [x] `conftest.py`/testes de
      `tests/unit/infrastructure/adapters/extractors/mariadb/` — mapeamento,
      construção preguiçosa, `listar_escopos`/`listar_tabelas`/`extrair_tabela`
      e o refinamento de BOOLEAN pela amostra, cobertos feliz/erro/borda
- [x] Teste de integração em `tests/integration/extractors/mariadb/` via
      `testcontainers` (`mariadb:11` real): inclui FK cross-database e
      promoção real de `tinyint(1)`→BOOLEAN
- [x] `pymysql`/`dbutils` adicionados às dependências, `testcontainers[mysql]`/
      `types-pymysql` ao grupo dev; override de mypy pra `dbutils.*`
      (sem stub oficial no PyPI, ao contrário do `types-psycopg2`)
- [x] `--import-mode=importlib` no `[tool.pytest.ini_options]` — necessário
      assim que uma segunda fonte trouxe um `test_mapeamento_de_tipos.py`
      com o mesmo nome de arquivo do Postgres, sem `__init__.py` nos
      diretórios de teste
- [x] `domain/model/{extraction,curation,analysis}.py` — reabertura de escopo
      da #44: `nao_nulavel`/`unica` em `ColunaExtraida`/`ColunaCurada`/
      `ColunaAnalisada`, campos estruturais (não métricas) no mesmo padrão de
      `chave_primaria`/`chave_estrangeira`
- [x] `ExtratorPostgres`/`ExtratorMariaDB` — captura de NOT NULL real do
      schema (`is_nullable`/`IS_NULLABLE`, mesma query já existente de
      colunas) e UNIQUE single-column (issue #44):
  - Postgres via catálogo `pg_index` (não `information_schema.
    table_constraints` como PK/FK — desvio deliberado pra cobrir num único
    passo tanto UNIQUE constraint nomeada quanto `CREATE UNIQUE INDEX`
    solto, que `table_constraints` não lista)
  - MariaDB via `information_schema.table_constraints`/`key_column_usage`,
    agrupando por `constraint_name` em Python pra ignorar UNIQUE composto —
    **bug real encontrado e reproduzido contra MariaDB 11 real** durante a
    revisão: nomes de constraint no MySQL/MariaDB são escopados por
    **tabela**, não por schema, então o JOIN precisa de
    `AND kcu.table_name = %s` explícito (o padrão de PK não precisava
    porque não faz esse JOIN) — sem isso, duas tabelas do mesmo schema com
    UNIQUE de mesmo nome (comum: `UNIQUE(email)`) geravam classificação
    cruzada e falso `unica=False`
  - `SobrescritaDeTabela._calcular_hash_estrutural` passou a incluir os dois
    campos novos — sem isso, mudança de NOT NULL/UNIQUE no banco não
    disparava aviso de estrutura alterada
- [x] Reabertura de escopo da #114 — streaming via cursor server-side +
      `AmostragemPorFaixa` (opt-in), motivada por RSS de pico ~900MB
      observado numa extração real (tabela outlier de 4,1M linhas/778MB):
  - `RequisicaoPorFaixa` (3º membro de `RequisicaoDeAmostragem`) +
    `AmostragemPorFaixa(EstrategiaDeAmostragem)`, opt-in — nunca troca
    silenciosa do default. `ExtratorPostgres` via `TABLESAMPLE SYSTEM ...
    REPEATABLE` (amostra por página física); `ExtratorMariaDB` via `K`
    faixas contíguas de PK sorteadas independentemente (sem PK inteira de
    coluna única, cai no fallback probabilístico já existente, com Aviso
    explicando o motivo). Todo Extrator emite Aviso de viés de cluster
    incondicional, texto próprio por motor.
  - `extractors/comum/ler_amostra_em_lotes.py` (um arquivo, três funções
    formando um único fluxo de decisão): `deve_usar_streaming` (limiar de
    linhas OU bytes estimados), `calcular_tamanho_lote` (bytes → nº de
    linhas por lote, com clamps), `ler_amostra_em_lotes` (`fetchmany` em
    lotes + `pl.concat`).
  - `ExtratorPostgres`: `_conexao(autocommit: bool = True)`, cursor
    nomeado + `itersize` acima do limiar, `commit()` explícito antes do
    `putconn`. `ExtratorMariaDB`: `SSCursor` acima do mesmo limiar,
    fechamento determinístico garantido pelo `with` já existente.
  - Largura média de linha por tabela: `pg_stats.avg_width` (Postgres,
    query nova agregada por schema) / `avg_row_length` (MariaDB, zero
    query nova, já lido junto de `table_rows`) — `LARGURA_MEDIA_PADRAO_
    BYTES = 200` como fallback quando o catálogo não tem estatística.
  - **2 bugs reais encontrados e corrigidos, nenhum reproduzível com
    dado sintético de teste:** (1) cursor nomeado do psycopg2 só popula
    `cursor.description` depois do 1º `fetchmany` — lido antes disso,
    devolvia nomes de coluna vazios silenciosamente; corrigido lendo
    `description` de dentro do loop, depois de cada fetch. (2)
    `pl.concat` estrito quebrava (`SchemaError`) quando um lote saía
    inteiro `NULL` numa coluna nulável (infere dtype `Null`) e o lote
    seguinte trazia um valor real pra essa coluna — corrigido com
    `pl.concat(lotes, how="vertical_relaxed")`. O 2º só apareceu ao
    rodar contra uma tabela de produção real (`token_acesso`), depois
    dos testes de integração via `testcontainers` já estarem verdes.
  - Limitação aceita, documentada, não testada: cursor nomeado do
    Postgres represa `VACUUM` no banco inteiro (não só na tabela lida)
    enquanto a transação estiver aberta — mitigado pelo gating por
    limiar, sem teste de carga concorrente de escrita (infraestrutura
    fora do escopo pragmático da issue).
  - Benchmark versionado (`test_extrator_postgres_benchmark_
    streaming.py`, marcado `benchmark`): não mostrou redução de RSS
    mensurável na escala sintética (1M linhas — a baseline fixa do
    processo domina), mas confirmado na prática contra o schema real que
    motivou a issue. Limiares de streaming (`100.000` linhas / `100MB`)
    e `K` faixas do MariaDB (`10`) seguem candidatos, não calibrados a
    um valor final.
- [x] Correções pós-banca de revisão da #114 (pré-PR) — arquiteto +
      engenheiro de dados + po-revisor revisaram o diff final em modo
      somente-leitura; 2 achados bloqueantes do engenheiro de dados,
      ambos validados empiricamente contra Postgres 16/MariaDB 11 reais
      (não hipóteses). Checklist completo com achados e correções em
      `plan/registry-plan/issue-114-streaming-e-amostragem-por-faixa.md`.
      Resumo:
  - **[Bloqueante] MariaDB:** `RAND(seed)` dentro de um `WHERE` é
    reavaliado por linha pelo motor, não sorteia um corte fixo — a
    amostra por faixa colapsava pros PKs mais baixos, independente do
    seed. Corrigido sorteando o corte em Python (`random.Random`), fixo
    por faixa, embutido como parâmetro literal.
  - **[Bloqueante] Postgres:** `pg_stats.avg_width` mede tamanho
    comprimido por TOAST, não o tamanho real transferido — subestimava
    a largura de colunas `text`/`json`/`bytea` em até ~85x, gerando
    lotes de streaming superestimados. Corrigido com uma sonda física
    (`TABLESAMPLE SYSTEM` + `octet_length`) só para tabelas com coluna
    TOAST-ável.
  - `MetadadosDeAmostra.estrategia` corrigido para refletir o mecanismo
    efetivo (não a Estrategia escolhida) no fallback do MariaDB;
    `pl.concat(how="vertical_relaxed")` restrito ao caso `Null`↔tipo-real
    (qualquer outra divergência de dtype entre lotes propaga erro); log
    estruturado (INFO) quando o streaming é ativado para uma tabela;
    `ler_amostra_fetchall` extraído como função irmã compartilhada
    (remove duplicação entre os dois Extratores no caminho não-streaming);
    `LARGURA_MEDIA_PADRAO_BYTES` unificado em `ler_amostra_em_lotes.py`.
  - Fora de escopo, registrado como follow-up: calibração formal dos
    limiares de streaming/`K` faixas (depende da correção de largura
    acima ter sido feita primeiro), checagem de PK monotônica na
    elegibilidade de faixa, teste de carga concorrente de escrita.
- [x] Paralelismo intra-tabela via `connectorx` (issue #126) — só
      `AmostragemIntegral`, nos dois motores. Checklist completo (achados
      da banca, resultado do spike de validação, decisões fechadas com o
      usuário) em
      `plan/registry-plan/issue-126-paralelismo-intra-tabela.md`. Resumo:
  - `extractors/comum/leitura_paralela_intra_tabela.py`
    (motor-agnóstico): `deve_paralelizar_leitura` (limiares candidatos:
    500.000 linhas / 500MB), `reservar_conexoes`/`liberar_conexoes`
    (reserva atômica sob `Lock` dedicado — resolve deadlock hold-and-wait
    entre líder e workers reservando do mesmo semáforo; reduz
    progressivamente até `MINIMO_CONEXOES_PARALELISMO=2`).
  - **Pivô de arquitetura em produção, não só planejamento:** uma
    primeira implementação (`ThreadPoolExecutor` + conexão `psycopg2` por
    faixa, snapshot via `pg_export_snapshot`/`SET TRANSACTION SNAPSHOT`)
    testada contra tabela real de ~4M linhas rendeu só ~15-20% de ganho
    (teto teórico 4x) — medição por thread confirmou o GIL do Python
    como gargalo estrutural na decodificação de `pl.DataFrame`. Spike de
    validação (`connectorx`, lib Rust que decodifica direto pra
    Arrow/Polars fora do GIL) confirmou 2.7-4x de ganho real na mesma
    tabela — decisão de refatorar a implementação existente pra
    `connectorx`, não abrir issue nova.
  - `ExtratorPostgres._ler_tabela_em_paralelo`: conexão líder exporta
    snapshot e mantém transação aberta; `n` faixas de `ctid`
    (`particoes_de_blocos`) viram uma lista de queries entregues numa
    única chamada `cx.read_sql(..., pre_execution_query=["BEGIN
    ISOLATION LEVEL REPEATABLE READ", "SET TRANSACTION SNAPSHOT
    '<id>'"])` — modo não documentado pela lib, validado empiricamente.
    Tabela particionada declarativamente cai no sequencial sem erro.
  - `ExtratorMariaDB._ler_tabela_em_paralelo`: sem conexão líder nem
    snapshot (sem equivalente no motor) — `MIN`/`MAX` de PK definem o
    domínio, `particionar_faixas_exaustivas` gera as faixas, elegível só
    com PK de coluna única e tipo inteiro (reusa
    `_elegibilidade_de_pk_para_faixa`, já existia pra
    `AmostragemPorFaixa`). Risco de inconsistência entre faixas aceito e
    documentado via `Aviso` único por execução (mesmo tratamento de
    ruído do achado B4 da #126, que a #116 já tinha corrigido pro viés
    de cluster).
  - **Risco real encontrado no spike, não resolvido nesta rodada:**
    `NUMERIC` sem precisão/escala fixa crasha `connectorx` de forma
    detectável (não trunca silenciosamente) quando linhas têm escalas
    diferentes.
  - Testes: unitários de partição por motor (`particoes_de_blocos`
    Postgres, `particionar_faixas_exaustivas` MariaDB, feliz/borda/erro)
    + testes de integração via `testcontainers` (Postgres 16 e MariaDB
    11 reais) confirmando conjunto de `id`s idêntico entre paralelo e
    sequencial, sem overlap nem gap. `ruff`/`mypy --strict` limpos, 665
    testes unitários+integração passando.
  - **Banca de revisão multi-agente pós-implementação** (arquiteto-de-
    software + engenheiro-de-dados + po-revisor, achados convergentes de
    2+ revisores independentes) — veredito inicial bloqueante, 4 achados
    corrigidos: (1) wizard não dava a mesma folga de `max_conexoes` ao
    MariaDB que já dava ao Postgres, paralelismo nunca ativava de verdade
    sob carga real; (2) sonda `MIN`/`MAX` do MariaDB reabria o semáforo
    depois da reserva, risco real de self-deadlock sem timeout — corrigido
    sondando antes de `reservar_conexoes`; (3) conexão líder do Postgres
    consumia 1 conexão real além do orçamento reservado — corrigido
    particionando em `n - 1` faixas; (4) crash do `connectorx` (ex.:
    `NUMERIC`) derrubava a tabela inteira em vez de cair pro sequencial —
    corrigido com fallback + `Aviso` legível. Achados importantes também
    corrigidos: `connect_timeout` não chegava às conexões do `connectorx`
    (corrigido no Postgres; testado empiricamente que o driver MySQL do
    `connectorx` rejeita esse parâmetro, risco aceito no MariaDB); teste
    de integração novo prova consistência da leitura paralela do Postgres
    sob escrita concorrente real (thread separada escrevendo durante toda
    a extração).
  - Fora de escopo, registrado como follow-up: `PercentualDeLinhas`/
    `AmostragemPorFaixa` com percentual alto (candidato a tratar como
    `AmostragemIntegral` pra elegibilidade), detecção de tabela
    particionada nativa do MariaDB, calibração final dos limiares,
    benchmark versionado (item 8 do registry-plan, ainda pendente),
    detecção prévia de `NUMERIC` sem escala fixa antes de tentar o
    caminho paralelo, sugestões de refatoração da banca (duplicação de
    `particionar_faixas_exaustivas`/`particoes_de_blocos`, unificação
    `_conexao`/`_conexao_ja_reservada`).

## 4. Sobrescrita (ACL Extraction → Curation) e OrquestradorParalelo

- [x] `SobrescritaDeTabela(Estagio[TabelaExtraida, TabelaCurada])`:
  - Hash SHA-256 de campos estruturais
  - Leitura de `overrides/<escopo>/<tabela>.yaml`
  - Geração de skeleton na primeira execução
  - Atualização idempotente (preserva curadoria, emite `Aviso` por mudança)
  - YAML malformado → `Falha` com mensagem clara
- [x] `OrquestradorParalelo(OrquestradorDeTabelas)`:
  - `extrair`: `ThreadPoolExecutor` para extração paralela; retorna
    `list[TabelaExtraida]`
  - `aplicar_sobrescritas`: `ThreadPoolExecutor` para sobrescrita paralela;
    agrega `list[TabelaCurada]` → `BancoCurado`
  - Acumulação de erros individuais sem interromper demais workers em ambas
    as fases

## 5. Analisadores

- [x] `AnalisadorDeMetricasDeColuna(Analisador)`:
  - `produz = [MetricasBaseColuna]`, `requer = []`
  - Calcula métricas via Polars: `percentual_nulo`, `percentual_unico`
    (nulos excluídos do numerador), `minimo`, `maximo`, `valores_frequentes`
    (`list[tuple[str, int]]`, nulos excluídos, desempate `count desc, valor
    asc`), `formato_detectado` (regex email/cpf/cnpj/phone/cep, threshold
    80% **e** mínimo absoluto de 20 valores não-nulos)
  - Guarda `tamanho_amostra == 0` antes de qualquer divisão
  - Normaliza com `MetadadosDeAmostra.tamanho_amostra`
  - Seta `tabela.amostra = None` após processar cada tabela (libera memória)
  - `Aviso` se `tamanho_amostra < 100`
- [x] `AnalisadorDeMetricasDeTabela(Analisador)`:
  - `produz = [MetricasBaseTabela]`, `requer = [MetricasBaseColuna]`
  - Calcula `completude` a partir de `MetricasBaseColuna` já presentes no
    `ContextoDeAnalise.analisado`, como média de `(100 - percentual_nulo)`
    das colunas; tabela sem colunas → `completude = 0.0`, sem dividir por
    zero
  - `Falha` defensiva se `MetricasBaseColuna` estiver ausente **ou
    duplicada** em qualquer coluna — interrompe no primeiro problema, sem
    processar as demais tabelas

## 6. Geradores concretos

- [x] `GeradorMarkdown(Gerador)`:
  - `requer = [MetricasBaseColuna, MetricasBaseTabela]`
  - Um `.md` por tabela + `index.md`
  - Nota de rodapé com `MetadadosDeAmostra` (estratégia, N amostrado, M total)
  - Reabertura de escopo da #44: coluna "Chave" renomeada pra "Restrição",
    acumulando `PK`/`FK`/`UNIQUE`/`NOT NULL` (antes só PK/FK) — suprimidos
    quando a coluna já é PK; `percentual_nulo` mostra "0.00% (garantido pelo
    schema)" quando `nao_nulavel=True`, combinando fato estrutural + métrica
    amostral só na apresentação; aviso de baixo sinal de "Valores frequentes
    por coluna" (antes só PK) generalizado pra `unica=True`, sem duplicar
    quando as duas são verdadeiras; seção "Valores frequentes por coluna"
    sempre renderiza o cabeçalho com uma nota quando nenhuma coluna é
    elegível (ex.: amostra vazia), em vez de desaparecer em silêncio —
    achado do usuário testando o artefato real (`docs_gerados/`)
  - Bugfix trivial e não relacionado, embutido na mesma issue (achado na
    revisão pós-merge da #13): `CategoriaDeDado.JSON` estava faltando em
    `_CATEGORIAS_SEM_MINIMO_E_MAXIMO` — mesmo bug de comparação
    lexicográfica já corrigido pras demais categorias textuais/estruturadas
- [x] `GeradorDbt(Gerador)`:
  - `requer = [MetricasBaseColuna]`
  - `dbt_project.yml` + `sources.yml` + `stg_<escopo>__<tabela>.sql` (cast com
    `TipoDeDado` rico; duplo underscore no nome do model, desvio deliberado
    do `stg_<tabela>` original — evita colisão entre escopos com tabela de
    mesmo nome) + `schema.yml` com testes sugeridos deterministicamente
  - `unique`/`not_null` combinam métrica amostral com o fato estrutural do
    schema (`unica`/`nao_nulavel`) — resolve a pendência da #44;
    `relationships` só quando a tabela referenciada está no lote analisado
    (senão `Aviso` + omissão); `accepted_values` com `severity: warn` e só
    quando os top-10 `valores_frequentes` cobrem ≥90% da amostra (é
    enumeração sobre amostra, não população — cobertura baixa dentro da
    própria amostra é sinal de lista longe de exaustiva)
  - Única saída cujos identificadores no artefato ficam em inglês (contrato do dbt)
  - Refactor embutido: `_escrever_arquivo` extraído para
    `generators/_escrita.py`, compartilhado com `GeradorMarkdown`
- [x] `GeradorContextoDeIA(Gerador)` (issue #15) — reabertura de escopo:
  substitui o `ai_context.json` monolítico original (redundante com
  Markdown/dbt) por três peças deriváveis do `BancoAnalisado`, sem
  Analisador novo nem dependência nova:
  - `requer = [MetricasBaseColuna]`
  - `index.json` com `grafo_de_relacionamentos` bidirecional via FK real
    (`chave_estrangeira`/`referencia`); `referencia` (saída) sempre
    exaustiva (vem do FK da própria tabela do lote), `referenciado_por`
    (entrada) só reflete tabelas presentes no lote — pode ser não-vazia
    mas incompleta se o lote for subconjunto da fonte, então o grafo carrega
    `nota_de_escopo` fixa avisando disso (não é `Aviso` por ocorrência,
    é limitação estrutural de toda execução)
  - `tabelas/<escopo>/<tabela>.json` — chunk por tabela, agrupado em
    subpasta por escopo (reabertura de escopo da #77, ver abaixo),
    endereçável independente do banco inteiro (schema linking)
  - `esquema_de_consulta.colunas_filtraveis` por tabela: sugestão de filtro
    `enum` quando a coluna não é PK, `tamanho_amostra >= 100` e cobertura
    dos top-10 `valores_frequentes` `>= 0.9` — reaproveita
    `_cobertura_dos_valores_frequentes`/`_COBERTURA_MINIMA_ACCEPTED_VALUES`
  - Refactor embutido: as duas acima extraídas de `gerador_dbt.py` para
    `generators/_metricas.py`, compartilhado entre os dois Geradores
  - Fora de escopo (decisão explícita, não implícita): inferir
    `papel_de_negocio`/`regras_de_negocio` a partir de estatísticas —
    exigiria exceção formal à Restrição 5 do PRD, fica para issue separada
  - Reabertura de escopo da #77 (extensão do mesmo padrão aplicado ao
    `GeradorDbt`, pedida pelo usuário após ver o resultado em uso real):
    `tabelas/<escopo>__<tabela>.json` achatado virou
    `tabelas/<escopo>/<tabela>.json`, sem prefixo de escopo no nome do
    arquivo — a subpasta já desambigua tabela homônima entre escopos,
    diferente do `_nome_model` do `GeradorDbt` (que precisa de nome
    globalmente único no grafo dbt)
- [x] `GeradorDbt` — reabertura de escopo da #77 (mini projeto dbt mais
  completo):
  - `models/staging/<escopo>/` autocontido (`sources.yml` + `.sql` por
    tabela + `schema.yml`), em vez de tudo achatado em `staging/` — convenção
    real dbt-labs pra staging multi-source, consistente com
    `stg_<escopo>__<tabela>` já usado pra evitar colisão de nome de model
  - `README.md` novo na raiz do projeto gerado, documentando escopos/
    tabelas cobertos e comandos básicos (`dbt run`/`dbt test`)
  - `_agrupar_por_escopo` extraído como helper compartilhado entre
    `_montar_sources`/`_renderizar_readme` (reuso real, mesmo loop)
  - Fora de escopo (avaliado e adiado, mesmo tratamento já dado à FK
    composta): `packages.yml`/`dbt_utils.unique_combination_of_columns`
    exigiria modelar UNIQUE composto estruturalmente (campo novo em
    `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada`, query nova nos dois
    Extratores, hash estrutural) — escopo maior que "mini projeto dbt",
    fica para issue futura. Camada intermediate, `profiles.yml`,
    `analyses/`, `exposures.yml`, `freshness` em sources e macros custom
    (validação de `formato_detectado`, teste "soft" de nulos/unicidade)
    também ficam de fora, registrados em
    `plan/registry-plan/issue-77-*.md`
- [x] `RestricaoUnica` + `restricoes_unicas` — reabertura de escopo da #89
  (fecha a pendência registrada acima na #77):
  - `RestricaoUnica` (Value Object novo, `domain/model/common/`) —
    `colunas: tuple[str, ...]`, `frozen=True`, mesmo padrão de
    `ReferenciaDeColuna`, validado (mínimo 2 colunas, sem duplicata)
  - `restricoes_unicas: list[RestricaoUnica]` em `TabelaExtraida`/
    `TabelaCurada`/`TabelaAnalisada` (nível tabela, mesmo padrão
    epistemológico de `nao_nulavel`/`unica` da #44); validator cruzado em
    `TabelaExtraida` garante que toda coluna citada existe na tabela;
    propaga para Curation/Analysis automaticamente via `model_dump`/
    `model_validate`, sem tocar em `iniciar_contexto`/`_traduzir`
  - `SobrescritaDeTabela._calcular_hash_estrutural` inclui
    `restricoes_unicas` — sem isso, UNIQUE composto criado/removido no
    banco não disparava aviso de estrutura alterada
  - `ExtratorPostgres`: query nova via `pg_index` + `unnest(indkey) WITH
    ORDINALITY`, substituindo o filtro `array_length = 1` que descartava
    compostos; 4 predicados adicionais (achados da banca de revisão,
    validados contra Postgres 16 real) evitam falsos positivos de índice
    de expressão, covering/`INCLUDE`, parcial (soft-delete) e inválido
  - `ExtratorMariaDB`: sem query nova — só reagrupamento Python
    (`_particionar_colunas_unicas`) sobre a mesma leitura já existente
    desde a #44; query ganhou `ORDER BY` (achado da banca — sem ordem
    garantida, o hash estrutural oscilaria sem mudança real de schema)
  - `GeradorDbt`: `packages.yml` condicional (só com `restricoes_unicas`
    no lote, removido se órfão) + teste model-level
    `dbt_utils.unique_combination_of_columns`, severidade padrão (`error`,
    diferente de `accepted_values`)
  - Fora de escopo, avaliado e adiado (mesmo tratamento da FK composta):
    `GeradorMarkdown`/`GeradorContextoDeIA` não renderizam
    `restricoes_unicas`, apesar de já renderizarem o análogo
    single-column (`unica`) — a issue #89 não pediu extensão desses dois
    Geradores; fica para issue futura se o usuário quiser essa simetria
  - Banca de revisão completa (Arquiteto de Software + Engenheiro de
    Dados + PO) antes da implementação, exigência explícita da própria
    issue por mudar contrato estrutural cross-context (mesmo risco/
    tamanho da #44) — achados incorporados ao plano antes do código,
    registrados em `plan/registry-plan/issue-89-*.md`
- [x] `GeradorDbt` — reabertura de escopo da #77 (macros dbt customizadas,
  issue #90): fecha duas métricas já calculadas por
  `AnalisadorDeMetricasDeColuna` mas nunca consumidas —
  `formato_detectado` e a faixa intermediária de nulo/unicidade que nem o
  fato estrutural do schema nem o `unique`/`not_null` "hard" alcançam:
  - `matches_format` (`macros/matches_format/`): dispatch por adapter, um
    arquivo por engine (Postgres via `~*`, MariaDB via `REGEXP`) — decisão
    da banca de revisão de planejamento de não centralizar num único
    arquivo com dispatch embutido, pra tornar o ponto de extensão visível
    no filesystem; engine sem implementação falha explícito
    (`default__validate_format`). Premissa técnica original (macro
    `dbt.regexp_like` builtin do dbt-core) verificada como incorreta pela
    banca antes da implementação — não existe, o dispatch precisou ser
    escrito do zero
  - Teste soft de nulo via `dbt_utils.not_null_proportion` (dependência já
    condicional desde a #89, sem macro novo); teste soft de unicidade via
    macro custom `unique_percentage_at_least.sql` (`dbt_utils` não tem
    equivalente de "% único") — thresholds 10%/95% (não 5%/90% como
    cogitado inicialmente), mais afastados da fronteira de ruído amostral
    perto do piso de 100 linhas, decisão confirmada com o usuário após
    exemplo numérico do erro padrão da proporção
  - `packages.yml` estendido: antes só `restricoes_unicas` (#89) acionava
    a escrita condicional, agora também `dbt_utils.not_null_proportion`
  - Banca de revisão do plano (Arquiteto de Software + Engenheiro de
    Dados + PO) antes da implementação, apesar de a própria issue não
    exigir isso — achados incorporados ao plano antes do código,
    registrados em `plan/registry-plan/issue-90-*.md`
- [x] `GeradorMarkdown`/`GeradorContextoDeIA` — reabertura de escopo da #89
  (issue #93): fecha a assimetria apontada pelo PO na revisão da #89 —
  `restricoes_unicas` (nível tabela) só era consumido pelo `GeradorDbt`:
  - `GeradorMarkdown`: marcador `"UNIQUE (composto)"` por coluna em
    `_marcadores_de_restricao` (participação, não mutuamente exclusivo com
    `"UNIQUE"` single-column) + bullet "Restrições UNIQUE compostas" em
    "Fatos extraídos" com os grupos completos
  - `GeradorContextoDeIA`: `restricoes_unicas: list[list[str]]` na raiz do
    JSON por tabela, chave omitida quando vazia (mesma convenção de
    `metricas_tabela`/`esquema_de_consulta`)
  - Grupos ordenados deterministicamente (`sorted` por tupla de colunas)
    nos dois Geradores — a ordem de extração vem do catálogo (OID/posição
    do índice), sem significado humano; sem ordenar, reextrações do mesmo
    schema lógico gerariam diff espúrio no artefato versionado. `GeradorDbt`
    não é tocado, mantém a ordem atual — fora do escopo desta issue
  - Banca de revisão do plano (Arquiteto de Software + Engenheiro de
    Dados + PO) rodada antes da implementação, apesar de a própria issue
    classificar o escopo como pequeno e dispensar banca completa —
    achados incorporados ao plano antes do código, registrados em
    `plan/registry-plan/issue-93-*.md`
- [x] Issue #95, Parte 1 — corrige falso positivo em `accepted_values`/
  sugestão de filtro `enum`: `_sugestoes_de_teste`/`_sugestao_de_filtro`
  decidiam "isso é categórico" só por `percentual_unico < 10.0` +
  cobertura, sem piso de amostra nem exclusão por tipo — sugeriu
  `accepted_values` para `criado_em` (TIMESTAMP), `produto_codigo`
  (código de catálogo crescente) e `quantidade` (baixa cardinalidade só
  na amostra) contra um banco de teste real:
  - `generators/_metricas.py`: função nova compartilhada
    `_elegivel_para_enumeracao` combina 5 critérios — categoria excluída
    (`TIMESTAMP`/`DATE`/`TIME`/`UUID`/`JSON`/`ARRAY`), piso de amostra
    (`_TAMANHO_AMOSTRA_MINIMO_ENUMERACAO = 100`, antes só existia no
    `GeradorContextoDeIA`), teto de cardinalidade real (`_contagem_de_distintos`
    reconstruída via `percentual_unico`, não `len(valores_frequentes)`
    truncado em top-10), `percentual_unico < 10.0` e cobertura ≥ 0.9
    (critérios originais)
  - `GeradorDbt`/`GeradorContextoDeIA` passam a chamar a função
    compartilhada em vez de reimplementar os critérios cada um
  - Detecção de código sequencial disfarçado de categórico (`PRD-N`)
    avaliada e adiada — exigiria inferência heurística sobre a forma do
    dado, mais próxima da linha que a Restrição 5 do PRD veda nesta
    versão do que uma regra determinística simples
- [x] Issue #95, Parte 2 — modela FK composta no dbt (fecha a limitação
  conhecida desde a #56) + simetria completa (Markdown/ContextoDeIA),
  mesma classe de risco/tamanho da #44/#89 (banca completa exigida e
  rodada antes da implementação — achados incorporados ao plano,
  registrados em `plan/registry-plan/issue-95-*.md`):
  - `RestricaoDeFkComposta` (Value Object novo,
    `domain/model/common/restricao_de_fk_composta.py`), mesmo padrão de
    `RestricaoUnica` — `colunas_locais`/`colunas_referenciadas` pareadas,
    `nome_escopo_referenciado`/`nome_tabela_referenciada`
  - `restricoes_fk_compostas: list[RestricaoDeFkComposta]` em
    `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada` (nível tabela, mesmo
    padrão epistemológico de `restricoes_unicas`); `ColunaExtraida.
    referencia` per-coluna fica **inalterado** — continua populado pra
    FK single-column e composta
  - `ExtratorPostgres`: query de FK ganha `constraint_name`/
    `ordinal_position` + `ORDER BY`; novo helper agnóstico de fonte
    `construir_restricoes_fk_compostas` (reaproveitado pelo MariaDB, zero
    query nova lá)
  - `OrquestradorParalelo.extrair`: `Aviso` quando FK composta não
    corresponde a PK/UNIQUE conhecida do lado referenciado — checagem
    cross-table, só possível depois que todas as tabelas do lote foram
    extraídas (achado da banca de revisão)
  - `SobrescritaDeTabela._calcular_hash_estrutural` inclui
    `restricoes_fk_compostas`
  - `GeradorDbt`: suprime `relationships` per-coluna pra colunas em FK
    composta; macro nova `composite_relationships` (SQL ANSI puro via
    `NOT EXISTS` + igualdade por coluna — sem tupla/`ROW` nem
    concatenação, achado do engenheiro-de-dados; semântica `MATCH SIMPLE`
    validada contra Postgres e MariaDB; severidade padrão `error`, mesmo
    critério de `unique_combination_of_columns`)
  - `GeradorMarkdown`/`GeradorContextoDeIA`: simetria completa pedida
    pelo PO já nesta issue (evita o retrabalho #89→#93) — bullet "Chaves
    estrangeiras compostas"/marcador `"FK (composta)"` (sem suprimir por
    PK, diferente de UNIQUE composto) e `restricoes_fk_compostas` (lista
    de dicts, não lista de listas) no JSON por tabela
  - Testes de integração novos contra Postgres 16 e MariaDB 11 reais
    (`testcontainers`) — fixture `geografia.pais`/`geografia.filial` (PK
    composta real), criada também no MariaDB (não existia)
- [x] Issue #105 — modela múltiplas FK numa mesma coluna, hoje descartada
  com Aviso. Evidência real: MariaDB gerenciado com 843 tabelas, 3
  colunas em produção com 2+ constraints FK de coluna única distintas
  apontando pra tabelas diferentes (FK polimórfica sem discriminator,
  achado durante o teste pós-implementação da #104). Diferente de FK
  composta (#95, 1 constraint com 2+ colunas) — aqui são 2+ constraints
  distintas de coluna única na mesma coluna; os dois mecanismos convivem
  sem conflito:
  - `ColunaExtraida`/`ColunaCurada`/`ColunaAnalisada`: `referencia:
    ReferenciaDeColuna | None` → `referencias: list[ReferenciaDeColuna]`
    (substitui o campo singular, não duplica); validator estrutural
    `_valida_referencia_de_chave_estrangeira` ajustado nos 3 modelos
  - `construir_colunas_fk` (helper compartilhado pelos dois Extratores)
    reescrito: agrupa por coluna sem descartar nada, retorna
    `dict[str, list[ReferenciaDeColuna]]`, sem `Aviso`/parâmetro `origem`
    (nada mais é perdido) — nenhuma query SQL nova, Postgres
    (`pg_constraint`) e MariaDB (`key_column_usage`) já retornam uma
    linha por constraint mesmo com 2+ constraints na mesma coluna
  - `SobrescritaDeTabela._calcular_hash_estrutural` inclui todas as
    referências da coluna, não só uma
  - `GeradorDbt`: achado bloqueante do engenheiro-de-dados na banca de
    revisão do plano — emitir um teste `relationships` por referência
    seria falso positivo garantido pra FK polimórfica sem discriminator
    (o teste assume "toda linha satisfaz a relação A", mas uma linha que
    aponta pra B falha). Coluna com 2+ referências não recebe
    `relationships` automático — emite `Aviso` explicando a ambiguidade
    em vez de testar
  - `GeradorMarkdown`/`GeradorContextoDeIA`: simetria completa "de
    graça" (efeito do loop substituindo valor único) — marcador `"FK →
    ..."` por referência no Markdown, `"referencias": [...]` sempre
    presente (mesmo vazia) no JSON por coluna do contexto de IA
  - Banca de revisão completa (Arquiteto de Software + Engenheiro de
    Dados + PO) antes da implementação, exigência explícita da própria
    issue por mudar contrato estrutural cross-context (mesmo critério de
    #44/#89/#95) — achados incorporados ao plano antes do código,
    registrados em `plan/registry-plan/issue-105-*.md`
  - Testes de integração novos contra Postgres 16 e MariaDB 11 reais
    (`testcontainers`) — fixture `polimorfismo.clientes`/
    `polimorfismo.fornecedores`/`polimorfismo.movimentos`, replicando o
    padrão real da issue

## 7. CLI real wizard (issue #16) — concluída

- [x] `cli/registro/` — `EXTRATORES_REGISTRADOS` (Postgres + MariaDB),
      `ESTRATEGIAS_REGISTRADAS`, `ANALISADORES_REGISTRADOS` (não exposto no
      wizard), `GERADORES_REGISTRADOS`; `registrar_ou_falhar()` em
      `comum.py` compartilhado pelos 4 `registrar_*`
- [x] `validar_dependencias(analisadores, geradores) -> Resultado[list[Analisador]]`
      em `cli/validacao.py` — verifica `produz`/`requer` antes de qualquer
      execução, devolve os Analisadores em ordem topológica
- [x] Fluxo completo do wizard (14 etapas, `wizard.py` só orquestra,
      implementação por fase em `cli/etapas/`):
      escolher estratégia de amostragem → escolher fonte e conectar (retry
      3x) → escolher escopos → extrair (paralelo) → gerar skeletons →
      **pausa para curadoria** → aplicar sobrescritas → escolher geradores →
      validar dependências → analisar → escolher destino → confirmar →
      executar
- [x] `Aviso`s exibidos em streaming por etapa concluída, agrupados por
      origem e por "tipo" (`cli/avisos.py`)
- [x] Código de saída `0`/`1` para uso em scripts e CI
- [x] Testes de CLI injetam `Extrator` fake via `EXTRATORES_REGISTRADOS` —
      nunca mockam o driver de baixo nível direto (`test_extracao.py`,
      `test_curadoria.py`, `test_analise.py`, `test_geracao.py`,
      `tests/integration/cli/test_wizard_end_to_end.py`)
- [x] `OrquestradorDeTabelas`/`OrquestradorParalelo` estendidos com sucesso
      parcial (falha individual vira `Aviso`, nunca aborta o lote) e
      `progresso: Callable[[str], None] | None` opcional
- [x] `Estagio.__call__` tornado positional-only — consistente com
      `Analisador`/`Gerador` (bug encontrado durante a implementação: a
      primeira combinação real de `compor()` com um `Analisador` em `src/`
      apareceu só aqui, fora do escopo anterior do `mypy --strict`)
- [x] `cli/etapas/geracao.py` — reabertura de escopo da #77 (bugfix): com
      2+ Geradores escolhidos na mesma execução, os artefatos caíam
      misturados no mesmo diretório. `executar_geradores` passa a escrever
      cada Gerador sempre em `destino/<slug>` (via `_slugificar`), mesmo
      quando só um é escolhido. `sugerir_destino` removida — o subpath por
      Gerador deixa de ser um caso especial de sugestão de texto e passa a
      ser sempre aplicado na escrita; `wizard.py` sugere só `"artefatos"`
      genérico
- [x] Issue #132 — restringe a extração a um subconjunto de tabelas dentro
      do(s) escopo(s) escolhido(s), antes obrigatoriamente completo. Banca
      de revisão (Arquiteto de Software + Engenheiro de Dados + PO +
      especialista-ux-terminal) rodada sobre o plano antes da implementação
      — checklist completo em
      `plan/registry-plan/issue-132-restringe-tabelas-do-escopo.md`:
  - `OrquestradorDeTabelas.extrair`: `escopos: list[str]` →
    `pares: list[tuple[str, str]]`, mudança de contrato não-aditiva —
    reabertura de escopo dentro da própria issue (não issue separada),
    decisão da banca. Deixa de listar tabelas por conta própria; quem
    chama já lista e decide o subconjunto antes. `ao_conhecer_total`
    removido junto — o total (`len(pares)`) já é conhecido pelo chamador
    antes de extrair, callback deixou de fazer sentido
  - `cli/etapas/extracao.py`: `listar_pares` (agrega
    `Extrator.listar_tabelas` por escopo, sucesso parcial via `Aviso`,
    mesma semântica que antes vivia dentro do Orquestrador) +
    `escolher_tabelas` (pergunta binária "extração completa do escopo"
    — default — vs. "escolher tabelas específicas"; só quem restringe vê
    o checkbox, vazio e com filtro por digitação, reperguntando se nada
    for marcado)
  - `prompts.escolher_multiplos` ganha `permite_vazio: bool = False` —
    só quando `True` a submissão vazia (não cancelamento) devolve `[]`
    em vez de sair do processo; call sites existentes inalterados
  - `wizard.py`: nova etapa sob o cabeçalho já existente "Escolher
    escopos" — sem `cabecalho_etapa` próprio, `_TOTAL_ETAPAS` continua
    11 (decisão do especialista-ux-terminal, precedente de `conectar()`,
    que já agrupa várias perguntas sob um único cabeçalho por serem a
    mesma decisão sendo detalhada, não fases distintas do pipeline)

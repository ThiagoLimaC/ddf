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

- [ ] `Aviso` (dataclass frozen) — `mensagem: str`, `origem: str`
- [ ] `Resultado[T]` como sum type — `Sucesso[T](valor, avisos: list[Aviso])` |
      `Falha(erro: str)`

### Modelos compartilhados (`domain/model/common`)

- [ ] `TipoDeDado` — `CategoriaDeDado` (Enum) +
      `precisao`/`escala`/`tamanho_maximo` opcionais
- [ ] `MetadadosDeAmostra` — `estrategia: str`, `tamanho_amostra: int`,
      `total_linhas: int`
- [ ] `ConfiguracaoDeExtracao` — `estrategia: EstrategiaDeAmostragem`,
      `max_trabalhadores`, `max_conexoes`; valida `max_conexoes >=
      max_trabalhadores` (sem `tamanho_amostra` — dimensionamento é
      responsabilidade de cada `EstrategiaDeAmostragem` concreta)

### Extraction Context (`domain/model/extraction.py`)

- [ ] `ColunaExtraida` — `nome`, `tipo_dado`, `chave_primaria`,
      `chave_estrangeira`, `referencia: ReferenciaDeColuna | None`
- [ ] `TabelaExtraida` — `nome_tabela`, `nome_escopo`,
      `colunas: list[ColunaExtraida]`, `total_linhas`,
      `amostra: pl.DataFrame | None`, `metadados_amostra`;
      `arbitrary_types_allowed=True`

### Curation Context (`domain/model/curation.py`)

- [ ] `ColunaCurada` — `ColunaExtraida` + `papel_de_negocio`,
      `regras_de_negocio`
- [ ] `TabelaCurada` — mesma estrutura de `TabelaExtraida` com `ColunaCurada` +
      `papel_de_negocio`, `regras_de_negocio`; `arbitrary_types_allowed=True`
- [ ] `BancoCurado` — `tabelas: list[TabelaCurada]`;
      `arbitrary_types_allowed=True`

### Analysis Context (`domain/model/analysis.py`)

- [ ] `MetricaDeColuna` (BaseModel frozen) — `origem: str` — Value Object base
- [ ] `MetricasBaseColuna(MetricaDeColuna)` — `percentual_nulo`, `percentual_unico`,
      `valores_frequentes`, `minimo`, `maximo`, `formato_detectado`;
      `origem = "AnalisadorDeMetricasDeColuna"`
- [ ] `MetricaDeTabela` (BaseModel frozen) — `origem: str` — Value Object base
- [ ] `MetricasBaseTabela(MetricaDeTabela)` — `completude: float`;
      `origem = "AnalisadorDeMetricasDeTabela"`
- [ ] `ColunaAnalisada` — campos de `ColunaCurada` +
      `metricas: list[MetricaDeColuna]`
- [ ] `TabelaAnalisada` — campos de `TabelaCurada` (sem amostra) +
      `metricas: list[MetricaDeTabela]` + `metadados_amostra`
- [ ] `BancoAnalisado` — `tabelas: list[TabelaAnalisada]`; Pydantic puro
- [ ] `ContextoDeAnalise` — `curado: BancoCurado`, `analisado: BancoAnalisado`;
      `arbitrary_types_allowed=True`
- [ ] `iniciar_contexto(curado: BancoCurado) -> ContextoDeAnalise` —
      constrói `BancoAnalisado` vazio a partir de `BancoCurado`

### Pipeline (`pipeline/`)

- [ ] `Estagio[Entrada, Saida]` (Protocol genérico) em `pipeline/estagio.py`
- [ ] `compor(*estagios)` em `pipeline/compor.py` — acumula avisos, para no
      primeiro `Falha`

### Ports (`domain/ports/`)

- [x] `Extrator` (Protocol) — `listar_escopos() -> Resultado[list[str]]`,
      `listar_tabelas(escopo) -> Resultado[list[tuple]]`,
      `extrair_tabela(escopo, tabela) -> Resultado[TabelaExtraida]`
      (issue #34: `listar_escopos` adicionado, vocabulário generalizado de `schema` para `escopo`)
- [ ] `Analisador` (Protocol) — `produz`, `requer`,
      `__call__(ContextoDeAnalise) -> Resultado[ContextoDeAnalise]`
- [ ] `Gerador` (Protocol) — `requer`,
      `__call__(BancoAnalisado, destino) -> Resultado[None]`
- [ ] `OrquestradorDeTabelas` (Protocol) — `extrair(escopos, extrator) ->
      Resultado[list[TabelaExtraida]]` + `aplicar_sobrescritas(tabelas, sobrescrita)
      -> Resultado[BancoCurado]`
- [ ] `EstrategiaDeAmostragem` (Protocol) — `nome: str`, `percentual: float`
      (política pura, sem SQL — cada Extrator traduz pro próprio dialeto)

### Contrato da CLI (`infrastructure/adapters/cli/`)

- [ ] `FONTES_REGISTRADAS` + `registrar_fonte()` em `cli/fontes.py` — registro
      de Extratores disponíveis; define o contrato de extensão desde o início
- [ ] `wizard.py` — esqueleto do fluxo completo com chamadas aos Ports já
      assinadas e comentários `# TODO: implementar na Task 7`; permite detectar
      cedo se o fluxo exige mudanças no modelo
- [ ] `validar_dependencias(analisadores, geradores) -> Resultado[None]` em
      `cli/validacao.py` — lógica pura, testável sem adapters concretos

- [ ] **Verificação:** testes de validação Pydantic (`percentual_nulo`/
      `percentual_unico` entre 0–100 em `MetricasBaseColuna`; `max_conexoes >=
      max_trabalhadores` em `ConfiguracaoDeExtracao`)

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

## 4. Sobrescrita (ACL Extraction → Curation) e OrquestradorParalelo

- [ ] `SobrescritaDeTabela(Estagio[TabelaExtraida, TabelaCurada])`:
  - Hash SHA-256 de campos estruturais
  - Leitura de `overrides/<escopo>/<tabela>.yaml`
  - Geração de skeleton na primeira execução
  - Atualização idempotente (preserva curadoria, emite `Aviso` por mudança)
  - YAML malformado → `Falha` com mensagem clara
- [ ] `OrquestradorParalelo(OrquestradorDeTabelas)`:
  - `extrair`: `ThreadPoolExecutor` para extração paralela; retorna
    `list[TabelaExtraida]`
  - `aplicar_sobrescritas`: `ThreadPoolExecutor` para sobrescrita paralela;
    agrega `list[TabelaCurada]` → `BancoCurado`
  - Acumulação de erros individuais sem interromper demais workers em ambas
    as fases

## 5. Analisadores

- [ ] `AnalisadorDeMetricasDeColuna(Analisador)`:
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
- [ ] `AnalisadorDeMetricasDeTabela(Analisador)`:
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
  - `tabelas/<escopo>__<tabela>.json` — chunk por tabela (mesma convenção
    de nome do `_nome_model` do dbt), endereçável independente do banco
    inteiro (schema linking)
  - `esquema_de_consulta.colunas_filtraveis` por tabela: sugestão de filtro
    `enum` quando a coluna não é PK, `tamanho_amostra >= 100` e cobertura
    dos top-10 `valores_frequentes` `>= 0.9` — reaproveita
    `_cobertura_dos_valores_frequentes`/`_COBERTURA_MINIMA_ACCEPTED_VALUES`
  - Refactor embutido: as duas acima extraídas de `gerador_dbt.py` para
    `generators/_metricas.py`, compartilhado entre os dois Geradores
  - Fora de escopo (decisão explícita, não implícita): inferir
    `papel_de_negocio`/`regras_de_negocio` a partir de estatísticas —
    exigiria exceção formal à Restrição 5 do PRD, fica para issue separada

## 7. CLI real wizard

- [ ] `FONTES_REGISTRADAS` + `registrar_fonte()` em `cli/fontes.py`
- [ ] `validar_dependencias(analisadores, geradores) -> Resultado[None]` em
      `cli/validacao.py` — verifica `produz`/`requer` antes de qualquer execução
- [ ] Fluxo completo do wizard:
      escolher fonte → conectar (retry 3x) → escolher escopos →
      extrair (paralelo) → gerar skeletons → **pausa para curadoria** →
      aplicar sobrescritas → validar dependências → analisar → escolher
      geradores → escolher destino → confirmar → executar
- [ ] `Aviso`s exibidos em streaming por etapa concluída
- [ ] Código de saída `0`/`1` para uso em scripts e CI
- [ ] Testes de CLI injetam `Extrator` fake via `FONTES_REGISTRADAS` — nunca
      mockam o driver de baixo nível direto

# Low Level Design — ddf (novo)

Este documento descreve a arquitetura de baixo nível do `ddf`: assinaturas,
parâmetros, tipos de retorno e comportamento esperado de cada componente,
organizados por Bounded Context.

---

## Shared (`src/ddf/domain/shared/`)

### `Aviso`

```python
@dataclass(frozen=True)
class Aviso:
    mensagem: str
    origem: str  # nome do Estagio que produziu (ex.: "ExtratorPostgres")
```

### `Resultado[T]`

```python
@dataclass(frozen=True)
class Sucesso(Generic[T]):
    valor: T
    avisos: list[Aviso] = field(default_factory=list)

@dataclass(frozen=True)
class Falha:
    erro: str  # mensagem legível por humano — nunca traceback crua
    avisos: list[Aviso] = field(default_factory=list)

Resultado = Sucesso[T] | Falha
```

**Comportamento:** todo Estagio que captura uma exceção esperada (conexão
recusada, arquivo ausente, YAML malformado) a converte em `Falha` com mensagem
clara antes de retornar. Nunca propaga exceção crua para fora de um Estagio.
`Falha.avisos` existe para que avisos emitidos antes do erro (por este Estagio
ou por Estagios anteriores em `compor()`) não sejam descartados silenciosamente
— a CLI exibe avisos em streaming, inclusive quando a execução termina em
`Falha`.

---

## Modelos compartilhados (`src/ddf/domain/model/common`)

### `TipoDeDado`

```python
class CategoriaDeDado(str, Enum):
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    TEXT = "TEXT"
    NUMERIC = "NUMERIC"
    FLOAT = "FLOAT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    TIME = "TIME"
    DATE = "DATE"
    JSON = "JSON"
    UUID = "UUID"
    UNKNOWN = "UNKNOWN"

class TipoDeDado(BaseModel):
    categoria: CategoriaDeDado
    precisao: int | None = None        # dígitos totais (NUMERIC)
    escala: int | None = None          # casas decimais (NUMERIC)
    tamanho_maximo: int | None = None  # tamanho máximo (VARCHAR)
    tamanho_fixo: int | None = None    # tamanho exato (CHAR)
    com_timezone: bool | None = None   # TIMESTAMP e TIME
    com_precisao_dupla: bool | None = None  # FLOAT (real vs. double precision)
```

**Comportamento:** imutável após construção. `UNKNOWN` quando o tipo da fonte
não mapeia para nenhuma categoria — nunca levanta exceção por tipo desconhecido.

**Adicionado na issue #9:** `FLOAT`, `CHAR`, `UUID`, `TIME` e os atributos
`tamanho_fixo`/`com_timezone`/`com_precisao_dupla` não existiam na issue #5
original — surgiram da necessidade de mapear `ExtratorPostgres` sem perder
informação relevante para o cast SQL do `GeradorDbt`. `FLOAT` (float binário
de largura fixa: `real`, `double precision`) foi deliberadamente separado de
`NUMERIC` (decimal exato com `precisao`/`escala` escolhidos pelo usuário) —
misturar os dois sob a mesma categoria produziria casts incorretos. Dentro de
`FLOAT`, `real` (4 bytes, ~6 dígitos) e `double precision` (8 bytes, ~15
dígitos) ainda são larguras diferentes — perder essa distinção também
produziria cast incorreto (`REAL` vs. `DOUBLE PRECISION` no destino), então
`com_precisao_dupla` capura isso, no mesmo padrão de `com_timezone`. `CHAR`
foi separado de `VARCHAR` pelo mesmo motivo original: comprimento fixo
(sempre preenchido com padding) não é o mesmo conceito que comprimento
máximo. `TIME` e `TIMESTAMP` compartilham `com_timezone` para capturar a
distinção `with/without time zone` do Postgres, que a v1 original desta issue
(`#5`/`#6`) não previa.

### `MetadadosDeAmostra`

```python
class MetadadosDeAmostra(BaseModel):
    estrategia: str      # "percentual_de_linhas", "full_scan"
    tamanho_amostra: int # linhas efetivamente amostradas
```

**Comportamento:** imutável. Viaja com `TabelaExtraida` e `TabelaCurada`.
Usado pelo Analisador para normalizar métricas (`percentual_nulo`,
`percentual_unico`) e pelos Geradores para anotar artefatos com a precisão
das estimativas.

**Sem `total_linhas` (removido na issue #9):** a versão original deste modelo
(issue #6) tinha um `total_linhas` próprio, descrito como "o universo que a
`EstrategiaDeAmostragem` considerou ao amostrar", distinto de
`TabelaExtraida.total_linhas`. Na prática, nenhum consumidor real usava essa
distinção — nem um `model_validator` (`tamanho_amostra <= total_linhas`)
chegou a ser implementado, nem o Analisador ou os Geradores liam esse campo
(os Geradores exibem `TabelaExtraida.total_linhas`, o total real). Era
complexidade especulativa para uma estratégia futura com filtro (`WHERE`) que
não existe. Removido — `TabelaExtraida.total_linhas` é a única fonte de
verdade para "quantas linhas a tabela tem".

### `ConfiguracaoDeExtracao`

```python
class ConfiguracaoDeExtracao(BaseModel):
    estrategia: EstrategiaDeAmostragem
```

**Comportamento:** lida de `ddf.toml` ou flags CLI (`--sample-percent`) —
único campo genuinamente compartilhável entre qualquer `Extrator` futuro,
sem exigir do usuário conhecimento específico de uma fonte concreta.

**Sem `max_trabalhadores`/`max_conexoes` (removidos na issue #10):** a versão
original (issue #5) tinha os dois campos aqui, com uma validação cruzada
(`max_conexoes >= max_trabalhadores`). Investigação da #10 mostrou que os
dois nunca precisavam ser números diferentes — cada chamada de `Extrator`
retém exatamente 1 conexão do pool por vez, e só o `OrquestradorParalelo`
dispara chamadas concorrentes contra ele. Concorrência segura virou
responsabilidade interna de cada `Extrator` concreto (ver `ExtratorPostgres`
abaixo, que ganhou um parâmetro `max_conexoes` próprio e um semáforo
interno) — `ConfiguracaoDeExtracao` deixou de carregar qualquer conceito de
concorrência, e o `OrquestradorParalelo` nunca a lê.

**Sem campo de tamanho de amostra:** dimensionar a amostra é responsabilidade
de cada `EstrategiaDeAmostragem` concreta (ex.: `PercentualDeLinhas.percentual`),
não de `ConfiguracaoDeExtracao` — o conceito de "tamanho" não generaliza para
estratégias futuras (`FullScan` não tem tamanho nem percentual).
`ConfiguracaoDeExtracao` orquestra concorrência; a estratégia decide como
amostrar. `MetadadosDeAmostra.tamanho_amostra` permanece como resultado
observado pelo `Extrator` após a amostragem, não como parâmetro de
configuração.

---

## Extraction Context (`src/ddf/domain/model/extraction.py`)

Representa a fonte de dados em sua forma mais crua — estrutura pura, sem
curadoria e sem métricas.

### `ColunaExtraida`

```python
class ColunaExtraida(BaseModel):
    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    referencia: ReferenciaDeColuna | None = None
```

**`referencia: ReferenciaDeColuna | None`** — Value Object compartilhado
(`domain/model/common/referencia_de_coluna.py`) com `nome_escopo`,
`nome_tabela`, `nome_coluna`. Substituiu `tabela_referenciada`/
`coluna_referenciada: str | None` soltos (issue #10, achado ao testar
contra um schema real multi-escopo): sem o escopo de destino, uma FK que
aponta pra uma tabela em **outro** escopo perdia essa informação — o modelo
só guardava o nome da tabela, nunca em qual escopo ela estava, deixando a
referência ambígua (ou errada) quando dois escopos tinham tabela com o
mesmo nome.

### `TabelaExtraida`

```python
class TabelaExtraida(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaExtraida]
    total_linhas: int                  # total real (information_schema)
    amostra: pl.DataFrame              # sempre preenchida pelo Extrator
    metadados_amostra: MetadadosDeAmostra
```

**Comportamento:** `amostra` é sempre preenchida pelo Extrator e obrigatória —
`TabelaExtraida` nunca chega ao Analisador (que só opera sobre `TabelaCurada`
via `ContextoDeAnalise.curado`), então não há estado intermediário em que ela
possa estar ausente aqui. Produzida pelo Extrator, consumida pela Sobrescrita.
O campo opcional (`pl.DataFrame | None`) e o descarte por liberação de memória
vivem em `TabelaCurada`, não em `TabelaExtraida` (ver seção Curation Context).

---

## Curation Context (`src/ddf/domain/model/curation.py`)

Adiciona curadoria humana sobre a estrutura extraída. Não contém métricas.

### `ColunaCurada`

```python
class ColunaCurada(BaseModel):
    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool = False
    chave_estrangeira: bool = False
    referencia: ReferenciaDeColuna | None = None
    papel_de_negocio: str | None = None     # adicionado neste contexto
    regras_de_negocio: list[str] = Field(default_factory=list)
```

### `TabelaCurada`

```python
class TabelaCurada(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaCurada]
    total_linhas: int
    papel_de_negocio: str | None = None
    regras_de_negocio: list[str] = Field(default_factory=list)
    amostra: pl.DataFrame | None        # mesmo DataFrame de TabelaExtraida — sem cópia; None após descarte
    metadados_amostra: MetadadosDeAmostra
```

**Comportamento:** o `pl.DataFrame` é passado por referência — sem cópia.
`None` após o Analisador descartar. Produzida pela Sobrescrita, consumida pelo
`OrquestradorParalelo` para agregação.

> **Nota sobre a Sobrescrita como ACL:** a Sobrescrita tem responsabilidade única
> — produzir `TabelaCurada` a partir de `TabelaExtraida`. Internamente, isso se
> desdobra em duas fases com razões de mudança distintas: `_traduzir` (mapeamento
> estrutural campo a campo) e `_aplicar_overrides` (aplicar curadoria do YAML).
> Não são dois componentes porque o resultado intermediário (uma `TabelaCurada`
> sem curadoria) não tem significado fora desse fluxo.

### `BancoCurado`

```python
class BancoCurado(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tabelas: list[TabelaCurada]
```

**Comportamento:** único agregado do Curation Context. Produzido pelo
`OrquestradorParalelo`. Único modelo além de `TabelaExtraida`/`TabelaCurada`
com `arbitrary_types_allowed=True` — os DataFrames vivem nas `TabelaCurada`
internas. Entregue ao Analisador via `ContextoDeAnalise`.

---

## Analysis Context (`src/ddf/domain/model/analysis.py`)

Métricas são **Value Objects** — imutáveis, sem identidade própria, definidos
pelos seus valores. Adicionar uma nova métrica = criar um novo tipo que herda
de `MetricaDeColuna` ou `MetricaDeTabela`. Zero mudanças no modelo existente.

### `MetricaDeColuna` (Value Object base)

```python
class MetricaDeColuna(BaseModel):
    model_config = ConfigDict(frozen=True)
    origem: str  # nome do Analisador que produziu
```

### `MetricasBaseColuna` (implementação concreta — `AnalisadorDeMetricasDeColuna`)

```python
class MetricasBaseColuna(MetricaDeColuna):
    origem: str = "AnalisadorDeMetricasDeColuna"
    percentual_nulo: float           # 0.0–100.0
    percentual_unico: float         # 0.0–100.0
    valores_frequentes: list[str]   # até 10 valores mais frequentes
    minimo: str | None               # representação string do mínimo
    maximo: str | None               # representação string do máximo
    formato_detectado: str | None   # "email", "cpf", "cnpj", "phone", "cep"
```

### `MetricaDeTabela` (Value Object base)

```python
class MetricaDeTabela(BaseModel):
    model_config = ConfigDict(frozen=True)
    origem: str
```

### `MetricasBaseTabela` (implementação concreta — `AnalisadorDeMetricasDeTabela`)

```python
class MetricasBaseTabela(MetricaDeTabela):
    origem: str = "AnalisadorDeMetricasDeTabela"
    completude: float  # média de (100 - m.percentual_nulo) das colunas
```

### `ColunaAnalisada`

```python
class ColunaAnalisada(BaseModel):
    nome: str
    tipo_dado: TipoDeDado
    chave_primaria: bool
    chave_estrangeira: bool
    referencia: ReferenciaDeColuna | None
    papel_de_negocio: str | None
    regras_de_negocio: list[str]
    metricas: list[MetricaDeColuna] = Field(default_factory=list)
```

**Comportamento:** `metricas` acumula Value Objects de múltiplos Analisadores
sem conflito. Um Gerador que quer `MetricasBaseColuna` filtra com
`next((m for m in col.metricas if isinstance(m, MetricasBaseColuna)), None)`.

### `TabelaAnalisada`

```python
class TabelaAnalisada(BaseModel):
    nome_tabela: str
    nome_escopo: str
    colunas: list[ColunaAnalisada]
    total_linhas: int
    papel_de_negocio: str | None
    regras_de_negocio: list[str]
    metadados_amostra: MetadadosDeAmostra  # preservado para Geradores anotarem artefatos
    metricas: list[MetricaDeTabela] = Field(default_factory=list)
```

### `BancoAnalisado`

```python
class BancoAnalisado(BaseModel):
    tabelas: list[TabelaAnalisada]
```

**Comportamento:** Pydantic puro — sem `arbitrary_types_allowed`. Nenhum
`pl.DataFrame`. Produzido pelo último Analisador do `compor()`, extraído do
`ContextoDeAnalise`. Consumido pelos Geradores.

### `ContextoDeAnalise`

```python
class ContextoDeAnalise(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    curado: BancoCurado          # fonte de dados raw (amostras pl.DataFrame)
    analisado: BancoAnalisado    # acúmulo de métricas calculadas
```

**Comportamento:** é a entrada e saída de cada `Analisador` no `compor()`.
Cada Analisador lê `curado` para acessar os DataFrames, lê `analisado` para
acessar métricas calculadas por Analisadores anteriores (ex.:
`AnalisadorDeMetricasDeTabela` lê `MetricasBaseColuna` calculadas pelo
`AnalisadorDeMetricasDeColuna`), e devolve um `ContextoDeAnalise` com
`analisado` enriquecido com suas próprias métricas. Os DataFrames em `curado`
são descartados conforme cada tabela é processada.

Utilitário de inicialização:

```python
def iniciar_contexto(curado: BancoCurado) -> ContextoDeAnalise:
    """Cria ContextoDeAnalise com BancoAnalisado vazio a partir do BancoCurado."""
    tabelas = [
        TabelaAnalisada(
            **t.model_dump(exclude={"colunas", "amostra"}),
            colunas=[
                ColunaAnalisada.model_validate(c.model_dump())
                for c in t.colunas
            ],
        )
        for t in curado.tabelas
    ]
    return ContextoDeAnalise(
        curado=curado,
        analisado=BancoAnalisado(tabelas=tabelas),
    )
```

**Por que `model_dump` + `model_validate`:** qualquer campo novo em
`ColunaCurada` que também exista em `ColunaAnalisada` é copiado
automaticamente — sem tocar em `iniciar_contexto`. Se um campo novo em
`ColunaCurada` não existir em `ColunaAnalisada`, `model_validate` levanta
`ValidationError`, forçando a decisão explícita. `exclude={"colunas", "amostra"}`
evita copiar o `pl.DataFrame` (não serializável via `model_dump`) e as colunas
(construídas separadamente).

---

## Pipeline (`src/ddf/pipeline/`)

### `Estagio` (`pipeline/estagio.py`)

```python
class Estagio(Protocol[Entrada, Saida]):
    def __call__(self, entrada: Entrada) -> Resultado[Saida]: ...
```

### `compor` (`pipeline/compor.py`)

```python
def compor(*estagios: Estagio) -> Estagio:
    """Compõe estágios em sequência, acumulando avisos e parando no 1º erro."""
```

**Comportamento:**
1. Executa cada Estagio em ordem, passando `.valor` do resultado anterior.
2. Acumula `avisos` de todos os Estagios bem-sucedidos.
3. Para no primeiro `Falha`, retornando-o com `Falha.avisos` preenchido pelos
   avisos acumulados até ali (incluindo os que o próprio Estagio que falhou
   possa ter emitido) — nenhum aviso é descartado silenciosamente.
4. Retorna `Sucesso(valor=resultado_final, avisos=todos_os_avisos)` se todos
   concluírem com sucesso.

---

## Ports (`src/ddf/domain/ports/`)

Todos os Ports abaixo (além de `EstrategiaDeAmostragem`, já existente) são
`@runtime_checkable`, permitindo `isinstance(fake, Port)` em testes.

`TipoDeMetrica = type[MetricaDeColuna | MetricaDeTabela]` — alias definido em
`domain/model/analysis.py` (junto dos tipos que referencia), usado em
`produz`/`requer` dos Ports `Analisador` e `Gerador`.

### `Extrator`

```python
@runtime_checkable
class Extrator(Protocol):
    def listar_escopos(self) -> Resultado[list[str]]: ...
    # lista os escopos disponíveis na fonte, ordenados por nome — schemas no
    # Postgres/SQL Server, databases no MySQL/MariaDB, etc.

    def listar_tabelas(
        self,
        escopo: str,
        /,
    ) -> Resultado[list[tuple[str, str]]]: ...
    # retorna list[(escopo, nome_tabela)] ordenada por nome_tabela
    # parâmetro positional-only (`/`) — adapters concretos podem usar outro
    # nome internamente (ex.: ExtratorPostgres usa "schema") sem quebrar em
    # runtime uma chamada por keyword feita contra o tipo Extrator

    def extrair_tabela(
        self,
        escopo: str,
        tabela: str,
        /,
    ) -> Resultado[TabelaExtraida]: ...
```

**Comportamento esperado de `listar_escopos`:**
- Lista os escopos (schemas, databases, ou o que a fonte concreta usar como
  nível de agrupamento acima de tabela) disponíveis na conexão atual.
- `Falha("Não foi possível conectar: <detalhe>")` se conexão recusada.

**Comportamento esperado de `extrair_tabela`:**
- Lê estrutura de `information_schema` (colunas, tipos, PKs, FKs).
- Lê `total_linhas` da tabela (fonte concreta decide como).
- Monta e executa a consulta de amostragem **no dialeto da própria fonte**,
  usando `configuracao.estrategia.percentual` como parâmetro — a
  `EstrategiaDeAmostragem` só descreve a política (quanto amostrar), nunca
  gera SQL (ver `EstrategiaDeAmostragem` abaixo).
- Constrói `TabelaExtraida` com `ColunaExtraida`s, `pl.DataFrame` e
  `MetadadosDeAmostra`.
- `Falha` legível nomeando o escopo/tabela não encontrados se inexistente —
  a redação exata é decisão de cada `Extrator` concreto, no vocabulário da
  própria fonte (`ExtratorPostgres` usa "Schema 'x' ou tabela 'y' não
  encontrada.", já que é assim que o Postgres chama a coisa; a Port não
  manda mais essa string específica como contrato).
- `Falha("Não foi possível conectar: <detalhe>")` se conexão recusada.

---

### `Analisador`

```python
@runtime_checkable
class Analisador(Protocol):
    produz: list[TipoDeMetrica]
    requer: list[TipoDeMetrica]

    def __call__(
        self,
        entrada: ContextoDeAnalise,
    ) -> Resultado[ContextoDeAnalise]: ...
```

**Comportamento esperado:**
- Lê `entrada.curado` para acessar os DataFrames via Polars.
- Lê `entrada.analisado` para acessar métricas de Analisadores anteriores.
- Acrescenta Value Objects do seu tipo à lista `metricas` de cada
  `ColunaAnalisada`/`TabelaAnalisada` — sem sobrescrever métricas existentes.
- Seta `tabela_curada.amostra = None` após processar cada tabela — libera
  memória sem quebrar o tipo (`amostra: pl.DataFrame | None`).
- Emite `Aviso` se amostra vazia ou muito pequena (< 100 linhas).
- `Falha` apenas em erro inesperado — amostra vazia é `Aviso`, não `Falha`.

---

### `Gerador`

```python
@runtime_checkable
class Gerador(Protocol):
    requer: list[TipoDeMetrica]

    def __call__(
        self,
        entrada: BancoAnalisado,
        destino: Path,
    ) -> Resultado[None]: ...
```

**Comportamento esperado:**
- Filtra as métricas que precisa com `isinstance`.
- Nunca levanta exceção se uma métrica declarada em `requer` estiver ausente —
  a validação acontece na CLI antes de qualquer Gerador rodar.
- `Falha("Não foi possível escrever em '<path>': <detalhe>")` em erro de disco.
- `avisos` pode incluir avisos sobre tabelas sem `papel_de_negocio`.

---

### `OrquestradorDeTabelas`

```python
@runtime_checkable
class OrquestradorDeTabelas(Protocol):
    def extrair(
        self,
        escopos: list[str],
        extrator: Extrator,
        /,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]: ...
```

**Comportamento esperado de `extrair`:**
- Lista tabelas via `extrator.listar_tabelas()` para cada escopo.
- Distribui `extrair_tabela()` em workers paralelos.
- Erros de tabelas individuais são acumulados — não interrompem as demais.
- Se qualquer tabela falhou: `Falha` com resumo de todas as falhas.

**Comportamento esperado de `aplicar_sobrescritas`:**
- Distribui `sobrescrita()` em workers paralelos sobre a lista recebida.
- Agrega `list[TabelaCurada]` em `BancoCurado` após todos terminarem.
- Erros individuais acumulados — mesma política de `extrair`.

**Razão da separação:** a CLI precisa pausar entre extração e aplicação de
sobrescritas para permitir curadoria humana dos skeletons gerados. Expor as
duas fases no Port evita que a pausa vaze para dentro do orquestrador ou force
re-extração do banco.

---

### `EstrategiaDeAmostragem`

```python
class EstrategiaDeAmostragem(Protocol):
    @property
    def nome(self) -> str: ...
    """Identificador usado em MetadadosDeAmostra.estrategia."""

    @property
    def percentual(self) -> float: ...
    """Fração da tabela a amostrar, em porcentagem (0, 100]."""
```

**Comportamento:** descreve só a *política* de amostragem (quanto amostrar),
nunca gera SQL. Traduzir isso numa consulta concreta é responsabilidade de
cada `Extrator` — que já é, por definição, acoplado ao dialeto da própria
fonte de dados. Isso evita que `EstrategiaDeAmostragem` (um Port pensado para
ser agnóstico de fonte, com fontes futuras como MariaDB/API/arquivo) precise
de uma implementação nova por banco só para gerar SQL diferente — o mesmo
`PercentualDeLinhas(percentual=5.0)` serve para qualquer `Extrator`, cada um
decidindo como aplicá-lo no próprio dialeto.

---

## Adapters — Extrator (`src/ddf/infrastructure/adapters/extractors/`)

### `ExtratorPostgres`

```python
class ExtratorPostgres:
    def __init__(
        self,
        dsn: str,
        configuracao: ConfiguracaoDeExtracao,
        max_conexoes: int = 8,
    ) -> None: ...
```

**Construção:** cria `ThreadedConnectionPool(minconn=1, maxconn=max_conexoes,
dsn=dsn)` e um `threading.Semaphore(max_conexoes)` interno. `max_conexoes` é
parâmetro próprio de `ExtratorPostgres` (não vem de `ConfiguracaoDeExtracao`,
que não carrega mais nenhum conceito de concorrência desde a issue #10) —
conhecimento específico de quanto este Postgres aguenta com segurança,
default `8`.

**Semáforo interno (issue #10):** `listar_tabelas`/`extrair_tabela` adquirem
o semáforo antes de `pool.getconn()` e o liberam depois de `pool.putconn()`
(ou de um erro de conexão). Isso garante que o pool nunca é solicitado além
de `max_conexoes` simultaneamente — se o `OrquestradorParalelo` disparar mais
chamadas concorrentes do que o pool aguenta, o excesso **espera** no
semáforo em vez de estourar `PoolError` (que `ThreadedConnectionPool.getconn()`
levantaria imediatamente, sem bloquear, caso o pool estivesse esgotado).

**`listar_escopos`:** query em `information_schema.schemata`, excluindo os
schemas de sistema do Postgres (`information_schema`, `pg_catalog`,
`pg_toast`, `pg_temp_%`, `pg_toast_temp_%`).

**`listar_tabelas`:** query em `information_schema.tables` filtrando
`table_type = 'BASE TABLE'`.

**`extrair_tabela`:**
1. Lê estrutura de `information_schema.columns` e constraints (`table_constraints`
   + `key_column_usage` para PK; + `constraint_column_usage` para o destino de
   cada FK — inclui `ccu.table_schema` além de `ccu.table_name`/`ccu.column_name`,
   pra `ReferenciaDeColuna` capturar FK que aponta pra outro escopo). O `JOIN`
   entre `table_constraints` e `constraint_column_usage` casa por
   `constraint_schema` (não `table_schema`) — `constraint_column_usage.table_schema`
   identifica a tabela *referenciada* pela FK, não a tabela onde ela foi
   declarada, então casar por `table_schema` excluiria toda FK cross-escopo
   do resultado (issue #10).
2. Mapeia tipos Postgres → `TipoDeDado` (tabela abaixo).
3. Lê `total_linhas` via `pg_catalog.pg_class.reltuples` — **estimativa**, não
   `COUNT(*)` exato. `information_schema.tables` não expõe contagem de linhas
   no Postgres (isso é comportamento do MySQL); `reltuples` é O(1) mas reflete
   a última `ANALYZE`/autovacuum, podendo estar desatualizado. Independente da
   amostragem (não é pré-requisito do passo seguinte) — usado só para
   preencher `TabelaExtraida.total_linhas`.
4. Monta e executa `SELECT * FROM {schema}.{tabela} TABLESAMPLE
   BERNOULLI(configuracao.estrategia.percentual)` e carrega em `pl.DataFrame`.
   `BERNOULLI` sorteia cada linha independentemente com probabilidade igual —
   amostra estatisticamente não enviesada, ao contrário de `LIMIT` sem
   `ORDER BY` (que reflete a ordem física/de inserção da tabela) e mais barata
   que `ORDER BY random() LIMIT N` (não exige sort completo da tabela).
5. `MetadadosDeAmostra.tamanho_amostra` é o número de linhas efetivamente
   retornadas pela amostra (`len(dataframe)`), não um valor calculado —
   `TABLESAMPLE` decide dinamicamente quantas linhas sorteia.
6. Retorna `TabelaExtraida`.

**Mapeamento de tipos:**

| Tipo Postgres (`information_schema.columns.data_type`) | `CategoriaDeDado` | Atributos extras |
|---|---|---|
| `character varying(n)` | `VARCHAR` | `tamanho_maximo=n` |
| `character(n)` | `CHAR` | `tamanho_fixo=n` |
| `text` | `TEXT` | — |
| `numeric(p,s)`, `decimal(p,s)` | `NUMERIC` | `precisao=p`, `escala=s` |
| `smallint`, `integer` | `INTEGER` | — |
| `bigint` | `BIGINT` | — |
| `real` | `FLOAT` | `com_precisao_dupla=False` |
| `double precision` | `FLOAT` | `com_precisao_dupla=True` |
| `boolean` | `BOOLEAN` | — |
| `timestamp without time zone` | `TIMESTAMP` | `com_timezone=False` |
| `timestamp with time zone` | `TIMESTAMP` | `com_timezone=True` |
| `time without time zone` | `TIME` | `com_timezone=False` |
| `time with time zone` | `TIME` | `com_timezone=True` |
| `date` | `DATE` | — |
| `json`, `jsonb` | `JSON` | — |
| `uuid` | `UUID` | — |
| qualquer outro | `UNKNOWN` | — |

**Justificativa das categorias novas (issue #9):** `FLOAT` foi separada de
`NUMERIC` porque `real`/`double precision` são float binário de largura fixa
pelo nome do tipo (sem `precisao`/`escala` escolhidos pelo usuário como em
`numeric(p,s)`) — misturar as duas sob a mesma categoria produziria um cast
SQL incorreto no `GeradorDbt`. Dentro de `FLOAT`, `real` (4 bytes) e `double
precision` (8 bytes) ainda têm larguras diferentes — `com_precisao_dupla`
distingue as duas, mesmo padrão de `com_timezone` em `TIME`/`TIMESTAMP`.
`CHAR` foi separada de `VARCHAR` pelo mesmo motivo: comprimento fixo (com
padding) não é o mesmo conceito que comprimento máximo. `UUID` e `TIME` não
tinham categoria equivalente antes desta issue.

### `PercentualDeLinhas`

```python
class PercentualDeLinhas:
    def __init__(self, percentual: float) -> None: ...
    # ValueError se percentual não estiver em (0, 100]

    @property
    def nome(self) -> str:
        """Retorna 'percentual_de_linhas'."""

    @property
    def percentual(self) -> float:
        """Retorna a fração da tabela a amostrar, em porcentagem (0, 100]."""
```

**Comportamento:** puramente uma política — não sabe nada de SQL nem do
banco de origem. Só guarda o percentual configurado; é o `ExtratorPostgres`
(ou qualquer `Extrator` futuro) quem decide como aplicá-lo.

**Por que percentual em vez de um LIMIT absoluto (`LimiteAleatorio`,
descartada nesta issue):** um valor absoluto fixo por execução (`--sample-size
500`) não escala entre tabelas de tamanhos muito diferentes — 500 linhas é
quase a tabela inteira numa tabela de 600 linhas, e uma fração irrisória numa
de 50 milhões. Calibrar isso por tabela é inviável numa CLI com dezenas de
tabelas.

**Por que a Estratégia não gera SQL (reabertura de decisão dentro da própria
#9):** a primeira versão de `PercentualDeLinhas` calculava um `LIMIT N` em
Python a partir de `total_linhas` para evitar `TABLESAMPLE` (sintaxe do
Postgres). Mas `LIMIT` sem `ORDER BY` retorna as linhas na ordem física da
tabela — enviesado, não uma amostra estatística de verdade. A correção óbvia
seria `TABLESAMPLE BERNOULLI` (sem viés) ou `ORDER BY random() LIMIT N` (sem
viés, mas cara — sort completo da tabela). Só que ambas exigem SQL específico
por Extrator de qualquer forma, então a decisão final foi: `EstrategiaDeAmostragem`
para de gerar SQL — vira só a política (`percentual`), e cada `Extrator`
(já necessariamente acoplado ao dialeto da própria fonte) decide a melhor
forma de amostrar sem viés no banco dele. `ExtratorPostgres` usa `TABLESAMPLE
BERNOULLI`. `tamanho_amostra=0` (percentual muito baixo numa tabela pequena)
é aceito como estado real, mesmo critério já usado em `MetadadosDeAmostra`
desde a #6.

---

## Adapters — Sobrescrita (`src/ddf/infrastructure/adapters/overrides/`)

### `SobrescritaDeTabela`

```python
class SobrescritaDeTabela:
    def __init__(self, diretorio_sobrescritas: Path) -> None: ...

    def __call__(self, entrada: TabelaExtraida) -> Resultado[TabelaCurada]: ...
```

**Comportamento:**
1. Calcula hash SHA-256 sobre `(nome_escopo, nome_tabela, [(col.nome,
   col.tipo_dado.model_dump_json(), col.chave_primaria, col.chave_estrangeira,
   col.referencia.model_dump_json() if col.referencia else "None") for col
   in colunas])` — `model_dump_json()` porque `TipoDeDado`/`ReferenciaDeColuna`
   são `BaseModel`, não primitivos hasheáveis diretamente; inclui o destino
   completo da FK (escopo + tabela + coluna, issue #10 reabre o hash
   original da #7/#8; mesma issue introduz `ReferenciaDeColuna` pra incluir
   o escopo de destino, corrigindo perda de informação em FK cross-escopo)
   pra detectar mudança de referência mesmo quando `chave_estrangeira`
   continua `True`.
2. Lê `diretorio_sobrescritas/<escopo>/<tabela>.yaml` se existir.
3. **Hash bate:** aplica `papel_de_negocio`/`regras_de_negocio` do YAML.
4. **Hash não bate (estrutura mudou):** atualiza skeleton preservando curadoria
   de colunas que ainda existem (por nome); emite um único `Aviso` por tabela,
   comparando os nomes de coluna do YAML com os da nova extração — cláusulas
   `colunas adicionadas`/`colunas removidas` (omitidas se vazias). Se os nomes
   de coluna são os mesmos mas o hash mudou (ex.: tipo ou FK de uma coluna
   existente mudou), emite uma mensagem genérica ("estrutura mudou, nomes
   preservados") — o hash é só no nível da tabela, não por coluna, então não
   dá pra apontar qual coluna específica mudou (ver nota abaixo).
5. **Arquivo não existe:** gera skeleton YAML e emite `Aviso` informando criação.
6. Retorna `TabelaCurada` com curadoria aplicada (ou campos vazios na 1ª vez).

**Formato do skeleton:**
```yaml
hash: "<sha256>"
papel_de_negocio: ""
regras_de_negocio: []
colunas:
  nome_da_coluna:
    papel_de_negocio: ""
    regras_de_negocio: []
```

**Erro esperado:** YAML malformado →
`Falha("Sobrescrita de '<escopo>.<tabela>' está malformada: <detalhe>")`.

**Possível melhoria futura (não implementada):** um hash por coluna (além do
hash da tabela) permitiria apontar exatamente qual coluna teve a estrutura
alterada num mismatch, em vez da mensagem genérica atual. Avaliado e adiado
na issue #10 — aumentaria a complexidade do skeleton sem um caso de uso
concreto ainda pedindo essa precisão.

---

## Adapters — Orquestrador (`src/ddf/infrastructure/adapters/orchestrator/`)

### `OrquestradorParalelo`

```python
class OrquestradorParalelo:
    def __init__(self, max_trabalhadores: int = 8) -> None: ...

    def extrair(
        self,
        escopos: list[str],
        extrator: Extrator,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]: ...
```

**`max_trabalhadores` (issue #10):** número genérico de chamadas concorrentes
por fase — higiene de recurso local (não criar threads demais pra um banco
com centenas de tabelas), sem nenhuma relação com concorrência segura contra
a fonte. Cada `Extrator` concreto já garante isso internamente (ver
`ExtratorPostgres`, que usa um semáforo próprio) — o Orquestrador nunca lê
`ConfiguracaoDeExtracao` nem nenhuma propriedade do `Extrator` além dos dois
métodos do Port.

**Comportamento de `extrair`:**
1. Lista tabelas por escopo — sequencial (operação leve). Falha de listagem
   de um escopo acumula (mesma política do item 3), não aborta os demais.
2. Distribui `extrair_tabela(escopo, tabela)` em `ThreadPoolExecutor(max_trabalhadores)`
   para todos os pares `(escopo, tabela)` listados com sucesso.
3. Acumula erros — de listagem e de extração — sem interromper outros workers.
4. `Falha("Falha ao extrair N de M tabelas: <escopo.tabela ou escopo>: <erro>; ...")`
   se qualquer escopo/tabela falhou — sem dado parcial dos que tiveram
   sucesso na mesma execução. Senão, `Sucesso` com `list[TabelaExtraida]`
   ordenada por `(nome_escopo, nome_tabela)` (`ThreadPoolExecutor` não
   garante ordem de conclusão).

**Comportamento de `aplicar_sobrescritas`:**
1. Distribui `sobrescrita(tabela)` em `ThreadPoolExecutor(max_trabalhadores)`.
2. Acumula erros sem interromper outros workers.
3. `Falha("Falha ao aplicar sobrescritas em N de M tabelas: <escopo.tabela>: <erro>; ...")`
   se qualquer tabela falhou; senão `Sucesso` com `BancoCurado` cujas
   `tabelas` estão ordenadas por `(nome_escopo, nome_tabela)`.

---

## Adapters — Analisadores (`src/ddf/infrastructure/adapters/analyzers/`)

### `AnalisadorDeMetricasDeColuna`

```python
class AnalisadorDeMetricasDeColuna:
    produz: list[type] = [MetricasBaseColuna]
    requer: list[type] = []

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]: ...
```

**Métricas calculadas por coluna (Polars):**

| Campo | Cálculo |
|---|---|
| `percentual_nulo` | `col.null_count() / tamanho_amostra * 100` |
| `percentual_unico` | `col.n_unique() / tamanho_amostra * 100` |
| `minimo` | `str(col.min())` — `None` se coluna inteiramente nula |
| `maximo` | `str(col.max())` — `None` se coluna inteiramente nula |
| `valores_frequentes` | top 10 valores por frequência, convertidos para `str` |
| `formato_detectado` | regex sobre valores não-nulos (ver abaixo) |

**Detecção de formato** (só em `VARCHAR`/`TEXT`, threshold ≥ 80% dos não-nulos):

| Formato | Regex |
|---|---|
| `email` | `r'^[\w.+-]+@[\w-]+\.[a-z]{2,}$'` |
| `cpf` | `r'^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$'` |
| `cnpj` | `r'^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$'` |
| `phone` | `r'^(\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}$'` |
| `cep` | `r'^\d{5}-?\d{3}$'` |

**Aviso emitido:** se `tamanho_amostra < 100`, emite `Aviso` por coluna.

---

### `AnalisadorDeMetricasDeTabela`

```python
class AnalisadorDeMetricasDeTabela:
    produz: list[type] = [MetricasBaseTabela]
    requer: list[type] = [MetricasBaseColuna]  # depende de percentual_nulo calculado

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]: ...
```

**Comportamento:** lê `MetricasBaseColuna` de cada `ColunaAnalisada` (já preenchida
pelo `AnalisadorDeMetricasDeColuna`), calcula `completude` como média de
`(100 - m.percentual_nulo)` e acrescenta `MetricasBaseTabela` à lista `metricas`
da `TabelaAnalisada`. `Falha` se `MetricasBaseColuna` estiver ausente em qualquer
coluna — a CLI valida a dependência antes de rodar, mas o Analisador também
valida defensivamente.

---

## Adapters — Geradores (`src/ddf/infrastructure/adapters/generators/`)

### `GeradorMarkdown`

```python
class GeradorMarkdown:
    requer: list[type] = [MetricasBaseColuna, MetricasBaseTabela]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

**Saída:** `<destino>/<escopo>/<tabela>.md` por tabela + `<destino>/index.md`.

**Conteúdo por arquivo:** nome, escopo, `total_linhas`, `completude`,
`papel_de_negocio`, `regras_de_negocio`, tabela de colunas com métricas, nota
de rodapé com `MetadadosDeAmostra` (estratégia, N amostrado, M total).

---

### `GeradorDbt`

```python
class GeradorDbt:
    requer: list[type] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

**Saída:** `dbt_project.yml`, `models/staging/sources.yml`,
`models/staging/stg_<tabela>.sql` por tabela, `models/staging/schema.yml`.

**Nota de idioma:** esta é a única saída do sistema cujo destino consome os
nomes diretamente (o próprio dbt e o warehouse). Por isso, e só aqui, os
identificadores gerados no artefato (nomes de coluna/tabela em `schema.yml`,
`sources.yml` e no SQL) permanecem em **inglês**, refletindo o contrato real
consumido pelo dbt — não o código Python do `GeradorDbt`, que segue a mesma
convenção de nomenclatura em português dos demais componentes.

**Testes sugeridos deterministicamente** (lidos de `MetricasBaseColuna`):

| Condição | Teste |
|---|---|
| `percentual_unico == 100.0` | `unique` |
| `percentual_nulo == 0.0` | `not_null` |
| `chave_estrangeira == True` | `relationships` |
| `valores_frequentes` não vazio e `percentual_unico < 10.0` | `accepted_values` |

**Cast SQL:** usa `TipoDeDado.categoria` + atributos de precisão para gerar
`CAST(col AS NUMERIC(10,2))` etc.

---

### `GeradorContextoDeIA`

```python
class GeradorContextoDeIA:
    requer: list[type] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

**Saída:** `<destino>/ai_context.json` — serialização compacta do
`BancoAnalisado`, incluindo todas as métricas (Value Objects serializados)
e `MetadadosDeAmostra` por tabela.

---

## CLI (`src/ddf/infrastructure/adapters/cli/`)

### `wizard.py`

```python
@click.command()
@click.option("--config", type=Path, default=None)
def executar(config: Path | None) -> None:
    """Executa o wizard interativo do ddf."""
```

**Etapas:**

1. Escolher fonte (`questionary.select` com `FONTES_REGISTRADAS`).
2. Informar credenciais (DSN ou campos separados).
3. Testar conexão — retry até 3 tentativas em falha.
4. Escolher escopo(s) (`questionary.checkbox`).
5. Extrair em paralelo via `OrquestradorParalelo` — exibe spinner + avisos.
6. Gerar skeletons de sobrescrita — exibe caminhos gerados.
7. **Pausa:** `questionary.confirm("Preencheu as sobrescritas? Pressione Enter para continuar.")`.
8. Aplicar sobrescritas — exibe avisos (colunas adicionadas/removidas).
9. **Validar dependências** Analisadores + Geradores antes de rodar qualquer um
    — `validar_dependencias` devolve os Analisadores já na ordem de execução.
10. Analisar via `compor(*analisadores_ordenados)` sobre `ContextoDeAnalise` —
    spinner + avisos.
11. Escolher Geradores (`questionary.checkbox`).
12. Escolher destino (`questionary.path`).
13. Confirmar — resumo do que será gerado.
14. Executar Geradores — progresso por Gerador + caminhos dos artefatos.

**Exibição de avisos:** após cada etapa, avisos acumulados são exibidos em
bloco formatado — nunca silenciosamente.

**Código de saída:** `0` em sucesso, `1` em qualquer `Falha`.

### Validação de dependências (`cli/validacao.py`)

```python
def validar_dependencias(
    analisadores: list[Analisador],
    geradores: list[Gerador],
) -> Resultado[list[Analisador]]:
    """Valida produz/requer e devolve os Analisadores em ordem de execução."""
```

**Comportamento:**
1. Ordena os Analisadores recebidos por dependência topológica de
   `produz`/`requer` — a ordem de seleção do usuário na CLI não determina a
   ordem de execução, só o conjunto selecionado.
2. Para cada Analisador: verifica que seus `requer` estão no conjunto `produz`
   dos Analisadores que vêm antes dele na ordem topológica calculada.
3. Para cada Gerador: verifica que seus `requer` estão no conjunto `produz`
   total dos Analisadores.
4. `Falha` com mensagem listando cada dependência não satisfeita e qual
   Analisador produziria ela.
5. `Falha` com mensagem clara se houver ciclo entre `produz`/`requer` dos
   Analisadores selecionados (ex.: A requer o que só B produz, e B requer o
   que só A produz).
6. Em sucesso, `Sucesso(valor=<analisadores ordenados>)` — o wizard usa esse
   valor diretamente em `compor(*analisadores_ordenados)`, sem recalcular a
   ordem.

### Registro de fontes (`cli/fontes.py`)

```python
FONTES_REGISTRADAS: dict[str, type[Extrator]] = {
    "PostgreSQL": ExtratorPostgres,
}

def registrar_fonte(
    nome: str,
    classe_extrator: type[Extrator],
    registro: dict[str, type[Extrator]] = FONTES_REGISTRADAS,
) -> None:
    """Registra uma nova fonte de dados no wizard."""
```

**Comportamento:** ponto de extensão para novas fontes sem editar o wizard.
`registro` tem `FONTES_REGISTRADAS` como default (uso normal do wizard), mas
aceita um dict isolado — testes de `registrar_fonte` injetam um registro
próprio em vez de mutar o dict global entre execuções. `ValueError` se `nome`
já existir em `registro` — nunca sobrescreve silenciosamente.

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

Resultado = Sucesso[T] | Falha
```

**Comportamento:** todo Estagio que captura uma exceção esperada (conexão
recusada, arquivo ausente, YAML malformado) a converte em `Falha` com mensagem
clara antes de retornar. Nunca propaga exceção crua para fora de um Estagio.

---

## Modelos compartilhados (`src/ddf/domain/model/common`)

### `TipoDeDado`

```python
class CategoriaDeDado(str, Enum):
    VARCHAR = "VARCHAR"
    TEXT = "TEXT"
    NUMERIC = "NUMERIC"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    DATE = "DATE"
    JSON = "JSON"
    UNKNOWN = "UNKNOWN"

class TipoDeDado(BaseModel):
    categoria: CategoriaDeDado
    precisao: int | None = None       # dígitos totais (NUMERIC)
    escala: int | None = None         # casas decimais (NUMERIC)
    tamanho_maximo: int | None = None # tamanho máximo (VARCHAR)
```

**Comportamento:** imutável após construção. `UNKNOWN` quando o tipo da fonte
não mapeia para nenhuma categoria — nunca levanta exceção por tipo desconhecido.

### `MetadadosDeAmostra`

```python
class MetadadosDeAmostra(BaseModel):
    estrategia: str      # "random_limit", "tablesample", "full_scan"
    tamanho_amostra: int # linhas efetivamente amostradas
    total_linhas: int    # total real da tabela (information_schema)
```

**Comportamento:** imutável. `tamanho_amostra <= total_linhas` sempre. Viaja
com `TabelaExtraida` e `TabelaCurada`. Usado pelo Analisador para normalizar
métricas e pelos Geradores para anotar artefatos com a precisão das
estimativas.

### `ConfiguracaoDeExtracao`

```python
class ConfiguracaoDeExtracao(BaseModel):
    tamanho_amostra: int = 10_000
    estrategia: EstrategiaDeAmostragem = Field(default_factory=LimiteAleatorio)
    max_trabalhadores: int = 8
    max_conexoes: int = 10
```

**Comportamento:** lida de `ddf.toml` ou flags CLI (`--sample-size`,
`--max-workers`). Valida `max_conexoes >=
max_trabalhadores` — `ValueError` com mensagem clara se violado.

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
    tabela_referenciada: str | None = None
    coluna_referenciada: str | None = None
```

### `TabelaExtraida`

```python
class TabelaExtraida(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_schema: str
    colunas: list[ColunaExtraida]
    total_linhas: int                  # total real (information_schema)
    amostra: pl.DataFrame | None        # None após o Analisador descartar para liberar memória
    metadados_amostra: MetadadosDeAmostra
```

**Comportamento:** `amostra` é sempre preenchida pelo Extrator. O Analisador
seta `None` após processar cada tabela para liberar memória. Código downstream
que tenta usar `amostra` após o descarte recebe `None` — tratado como `Aviso`
defensivo dentro do Analisador. Produzida pelo Extrator, consumida pela
Sobrescrita.

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
    tabela_referenciada: str | None = None
    coluna_referenciada: str | None = None
    papel_de_negocio: str | None = None     # adicionado neste contexto
    regras_de_negocio: list[str] = Field(default_factory=list)
```

### `TabelaCurada`

```python
class TabelaCurada(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nome_tabela: str
    nome_schema: str
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

### `MetricasBase` (implementação concreta — `AnalisadorDeMetricasDeColuna`)

```python
class MetricasBase(MetricaDeColuna):
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

### `MetricasDeTabela` (implementação concreta — `AnalisadorDeMetricasDeTabela`)

```python
class MetricasDeTabela(MetricaDeTabela):
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
    tabela_referenciada: str | None
    coluna_referenciada: str | None
    papel_de_negocio: str | None
    regras_de_negocio: list[str]
    metricas: list[MetricaDeColuna] = Field(default_factory=list)
```

**Comportamento:** `metricas` acumula Value Objects de múltiplos Analisadores
sem conflito. Um Gerador que quer `MetricasBase` filtra com
`next((m for m in col.metricas if isinstance(m, MetricasBase)), None)`.

### `TabelaAnalisada`

```python
class TabelaAnalisada(BaseModel):
    nome_tabela: str
    nome_schema: str
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
`AnalisadorDeMetricasDeTabela` lê `MetricasBase` calculadas pelo
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
3. Para no primeiro `Falha`, retornando-o com os avisos acumulados até ali.
4. Retorna `Sucesso(valor=resultado_final, avisos=todos_os_avisos)` se todos
   concluírem com sucesso.

---

## Ports (`src/ddf/domain/ports/`)

### `Extrator`

```python
class Extrator(Protocol):
    def listar_tabelas(
        self,
        schema: str,
    ) -> Resultado[list[tuple[str, str]]]: ...
    # retorna list[(schema, nome_tabela)] ordenada por nome_tabela

    def extrair_tabela(
        self,
        schema: str,
        tabela: str,
    ) -> Resultado[TabelaExtraida]: ...
```

**Comportamento esperado de `extrair_tabela`:**
- Lê estrutura de `information_schema` (colunas, tipos, PKs, FKs).
- Executa `configuracao.estrategia.consulta(schema, tabela)` para amostrar dados.
- Constrói `TabelaExtraida` com `ColunaExtraida`s, `pl.DataFrame` e
  `MetadadosDeAmostra`.
- `Falha("Schema 'x' ou tabela 'y' não encontrada.")` se inexistente.
- `Falha("Não foi possível conectar: <detalhe>")` se conexão recusada.

---

### `Analisador`

```python
class Analisador(Protocol):
    produz: list[type[MetricaDeColuna | MetricaDeTabela]]
    requer: list[type[MetricaDeColuna | MetricaDeTabela]]

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
class Gerador(Protocol):
    requer: list[type[MetricaDeColuna | MetricaDeTabela]]

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
class OrquestradorDeTabelas(Protocol):
    def extrair(
        self,
        schemas: list[str],
        extrator: Extrator,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]: ...
```

**Comportamento esperado de `extrair`:**
- Lista tabelas via `extrator.listar_tabelas()` para cada schema.
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

    def consulta(self, schema: str, tabela: str) -> str: ...
    """Retorna a SQL de amostragem para a tabela especificada."""
```

---

## Adapters — Extrator (`src/ddf/infrastructure/adapters/extractors/`)

### `ExtratorPostgres`

```python
class ExtratorPostgres:
    def __init__(self, dsn: str, configuracao: ConfiguracaoDeExtracao) -> None: ...
```

**Construção:** cria `ThreadedConnectionPool(minconn=1,
maxconn=configuracao.max_conexoes, dsn=dsn)`. Valida `max_conexoes >=
max_trabalhadores`.

**`listar_tabelas`:** query em `information_schema.tables` filtrando
`table_type = 'BASE TABLE'`.

**`extrair_tabela`:**
1. Lê estrutura de `information_schema.columns` e constraints.
2. Mapeia tipos Postgres → `TipoDeDado` (tabela abaixo).
3. Lê `total_linhas` via `information_schema.tables`.
4. Executa `configuracao.estrategia.consulta(schema, tabela)` e carrega em
   `pl.DataFrame`.
5. Retorna `TabelaExtraida`.

**Mapeamento de tipos:**

| Tipo Postgres | `CategoriaDeDado` | Atributos extras |
|---|---|---|
| `varchar(n)`, `character varying(n)` | `VARCHAR` | `tamanho_maximo=n` |
| `text` | `TEXT` | — |
| `numeric(p,s)`, `decimal(p,s)` | `NUMERIC` | `precisao=p`, `escala=s` |
| `integer`, `int4` | `INTEGER` | — |
| `bigint`, `int8` | `BIGINT` | — |
| `boolean` | `BOOLEAN` | — |
| `timestamp`, `timestamptz` | `TIMESTAMP` | — |
| `date` | `DATE` | — |
| `json`, `jsonb` | `JSON` | — |
| qualquer outro | `UNKNOWN` | — |

### `LimiteAleatorio`

```python
class LimiteAleatorio:
    def __init__(self, tamanho: int) -> None: ...

    @property
    def nome(self) -> str:
        """Retorna 'random_limit'."""

    def consulta(self, schema: str, tabela: str) -> str:
        """Retorna: SELECT * FROM {schema}.{tabela} LIMIT {tamanho}"""
```

---

## Adapters — Sobrescrita (`src/ddf/infrastructure/adapters/overrides/`)

### `SobrescritaDeTabela`

```python
class SobrescritaDeTabela:
    def __init__(self, diretorio_sobrescritas: Path) -> None: ...

    def __call__(self, entrada: TabelaExtraida) -> Resultado[TabelaCurada]: ...
```

**Comportamento:**
1. Calcula hash SHA-256 sobre `(nome_tabela, nome_schema, [(col.nome,
   col.tipo_dado, col.chave_primaria, col.chave_estrangeira) for col in colunas])`.
2. Lê `diretorio_sobrescritas/<schema>/<tabela>.yaml` se existir.
3. **Hash bate:** aplica `papel_de_negocio`/`regras_de_negocio` do YAML.
4. **Hash não bate (estrutura mudou):** atualiza skeleton preservando curadoria
   de colunas que ainda existem; emite `Aviso` com colunas adicionadas/removidas.
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
`Falha("Sobrescrita de '<schema>.<tabela>' está malformada: <detalhe>")`.

---

## Adapters — Orquestrador (`src/ddf/infrastructure/adapters/orchestrator/`)

### `OrquestradorParalelo`

```python
class OrquestradorParalelo:
    def __init__(self, max_trabalhadores: int = 8) -> None: ...

    def extrair(
        self,
        schemas: list[str],
        extrator: Extrator,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]: ...
```

**Comportamento de `extrair`:**
1. Lista tabelas por schema — sequencial (operação leve).
2. Distribui `extrair_tabela(schema, tabela)` em `ThreadPoolExecutor(max_trabalhadores)`.
3. Acumula erros sem interromper outros workers.
4. `Falha` com resumo se qualquer tabela falhou; senão retorna `list[TabelaExtraida]`.

**Comportamento de `aplicar_sobrescritas`:**
1. Distribui `sobrescrita(tabela)` em `ThreadPoolExecutor(max_trabalhadores)`.
2. Acumula erros sem interromper outros workers.
3. `Falha` com resumo se qualquer tabela falhou; senão agrega em `BancoCurado`.

---

## Adapters — Analisadores (`src/ddf/infrastructure/adapters/analyzers/`)

### `AnalisadorDeMetricasDeColuna`

```python
class AnalisadorDeMetricasDeColuna:
    produz: list[type] = [MetricasBase]
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
    produz: list[type] = [MetricasDeTabela]
    requer: list[type] = [MetricasBase]  # depende de percentual_nulo calculado

    def __call__(self, entrada: ContextoDeAnalise) -> Resultado[ContextoDeAnalise]: ...
```

**Comportamento:** lê `MetricasBase` de cada `ColunaAnalisada` (já preenchida
pelo `AnalisadorDeMetricasDeColuna`), calcula `completude` como média de
`(100 - m.percentual_nulo)` e acrescenta `MetricasDeTabela` à lista `metricas`
da `TabelaAnalisada`. `Falha` se `MetricasBase` estiver ausente em qualquer
coluna — a CLI valida a dependência antes de rodar, mas o Analisador também
valida defensivamente.

---

## Adapters — Geradores (`src/ddf/infrastructure/adapters/generators/`)

### `GeradorMarkdown`

```python
class GeradorMarkdown:
    requer: list[type] = [MetricasBase, MetricasDeTabela]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

**Saída:** `<destino>/<schema>/<tabela>.md` por tabela + `<destino>/index.md`.

**Conteúdo por arquivo:** nome, schema, `total_linhas`, `completude`,
`papel_de_negocio`, `regras_de_negocio`, tabela de colunas com métricas, nota
de rodapé com `MetadadosDeAmostra` (estratégia, N amostrado, M total).

---

### `GeradorDbt`

```python
class GeradorDbt:
    requer: list[type] = [MetricasBase]

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

**Testes sugeridos deterministicamente** (lidos de `MetricasBase`):

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
    requer: list[type] = [MetricasBase]

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
4. Escolher schema(s) (`questionary.checkbox`).
5. Extrair em paralelo via `OrquestradorParalelo` — exibe spinner + avisos.
6. Gerar skeletons de sobrescrita — exibe caminhos gerados.
7. **Pausa:** `questionary.confirm("Preencheu as sobrescritas? Pressione Enter para continuar.")`.
8. Aplicar sobrescritas — exibe avisos (colunas adicionadas/removidas).
9. **Validar dependências** Analisadores + Geradores antes de rodar qualquer um.
10. Analisar via `compor(*analisadores)` sobre `ContextoDeAnalise` — spinner + avisos.
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
) -> Resultado[None]:
    """Valida que todos os requer de Analisadores e Geradores estão satisfeitos."""
```

**Comportamento:**
1. Coleta `produz` de todos os Analisadores selecionados.
2. Para cada Analisador: verifica que seus `requer` estão no conjunto `produz`
   dos Analisadores que vêm antes dele na ordem de execução.
3. Para cada Gerador: verifica que seus `requer` estão no conjunto `produz`
   total dos Analisadores.
4. `Falha` com mensagem listando cada dependência não satisfeita e qual
   Analisador produziria ela.

### Registro de fontes (`cli/fontes.py`)

```python
FONTES_REGISTRADAS: dict[str, type[Extrator]] = {
    "PostgreSQL": ExtratorPostgres,
}

def registrar_fonte(nome: str, classe_extrator: type[Extrator]) -> None:
    """Registra uma nova fonte de dados no wizard."""
```

**Comportamento:** ponto de extensão para novas fontes sem editar o wizard.
Testes de CLI injetam `Extrator` fake via `FONTES_REGISTRADAS`.

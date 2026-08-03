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
    ENUM = "ENUM"
    SET = "SET"
    UNKNOWN = "UNKNOWN"

class TipoDeDado(BaseModel):
    categoria: CategoriaDeDado
    precisao: int | None = None        # dígitos totais (NUMERIC)
    escala: int | None = None          # casas decimais (NUMERIC)
    tamanho_maximo: int | None = None  # tamanho máximo (VARCHAR)
    tamanho_fixo: int | None = None    # tamanho exato (CHAR)
    com_timezone: bool | None = None   # TIMESTAMP e TIME
    com_precisao_dupla: bool | None = None  # FLOAT (real vs. double precision)
    valores_permitidos: tuple[str, ...] | None = None  # ENUM e SET
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

**Adicionado na issue #35:** `ENUM`, `SET` e o atributo `valores_permitidos`
(tupla imutável dos valores aceitos) — MariaDB é a primeira fonte a modelar
essas categorias nativamente; os dois tipos compartilham `valores_permitidos`
porque a única diferença semântica entre eles (um valor vs. múltiplos valores
simultâneos por linha) não afeta como `ExtratorMariaDB`, `GeradorMarkdown` e
`GeradorDbt` consomem o atributo. Sem equivalente ANSI portável, `GeradorDbt`
faz cast para `VARCHAR` (ver seção do `GeradorDbt`).

### `MetadadosDeAmostra`

```python
class MetadadosDeAmostra(BaseModel):
    estrategia: str               # "percentual_de_linhas", "tabela_inteira"
    tamanho_amostra: int          # linhas efetivamente amostradas
    percentual: float | None = None  # None em tabela_inteira
    seed: int | None = None          # None em tabela_inteira
```

**Comportamento:** imutável. Viaja com `TabelaExtraida` e `TabelaCurada`.
Usado pelo Analisador para normalizar métricas (`percentual_nulo`,
`percentual_unico`) e pelos Geradores para anotar artefatos com a precisão
das estimativas.

**`percentual`/`seed` (issue #76):** valores efetivamente usados na consulta
(não os configurados) — em amostragem probabilística sem `seed` explícito, o
Extrator gera um antes de montar a query e é esse valor gerado que aparece
aqui, nunca `None`. Sem isso, reprodutibilidade não seria verificável a
partir do artefato gerado (`GeradorContextoDeIA`/`GeradorMarkdown` exibem os
dois). Ambos ficam `None` em `tabela_inteira`, que não tem política
probabilística nenhuma.

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
    estrategia: EstrategiaDeAmostragem | None = None

    def estrategia_obrigatoria(self) -> Resultado[EstrategiaDeAmostragem]:
        """Falha explícita se `estrategia` ainda for None."""
```

**Comportamento:** lida de `ddf.toml` ou flags CLI (`--sample-percent`) —
único campo genuinamente compartilhável entre qualquer `Extrator` futuro,
sem exigir do usuário conhecimento específico de uma fonte concreta.

**`estrategia` opcional, atribuída depois da construção (issue #75):** o
wizard reordenado (`cli/etapas/extracao.py::conectar()`) constrói o
Extrator e testa conexão antes de perguntar a estratégia de amostragem —
`configurar_amostragem()` a atribui depois, mutando a mesma instância de
`ConfiguracaoDeExtracao` que o Extrator já guarda por referência (não é
`frozen=True`). `estrategia_obrigatoria()` centraliza a checagem que todo
`Extrator.extrair_tabela` faz antes de usar `estrategia` — `Falha` explícita
em vez de `AttributeError`, e evita cada Adapter concreto reimplementar o
mesmo guard manualmente.

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
de cada `EstrategiaDeAmostragem` concreta (ex.:
`PercentualDeLinhas.requisicao.percentual`), não de `ConfiguracaoDeExtracao` —
o conceito de "tamanho" não generaliza para todas as estratégias (`TabelaInteira`,
implementada na issue #76, não tem tamanho nem percentual — só `nome` e
`requisicao`, ver `EstrategiaDeAmostragem` abaixo). `ConfiguracaoDeExtracao`
orquestra concorrência; a estratégia decide como amostrar.
`MetadadosDeAmostra.tamanho_amostra` permanece como resultado observado pelo
`Extrator` após a amostragem, não como parâmetro de configuração.

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
    referencias: list[ReferenciaDeColuna] = Field(default_factory=list)
    nao_nulavel: bool = False  # NOT NULL real do schema
    unica: bool = False        # UNIQUE single-column real do schema (PK excluída)
```

**`nao_nulavel`/`unica` (issue #44):** fatos estruturais do schema, no mesmo
nível epistemológico de `chave_primaria`/`chave_estrangeira` — lidos do
catálogo da fonte, não calculados sobre amostra. Por isso são campos simples
aqui, não um novo `MetricaDeColuna` (ver `MetricasBaseColuna` abaixo, que
não muda). `unica=True` significa "unicidade single-column garantida pelo
schema": uma constraint UNIQUE composta de 2+ colunas não marca nenhuma
coluna individual como única — esse caso é deliberadamente não representado.

**`referencias: list[ReferenciaDeColuna]`** — uma entrada por constraint FK
de coluna única que referencia esta coluna. `ReferenciaDeColuna` é um Value
Object compartilhado (`domain/model/common/referencia_de_coluna.py`) com
`nome_escopo`, `nome_tabela`, `nome_coluna`. Substituiu `tabela_referenciada`/
`coluna_referenciada: str | None` soltos (issue #10, achado ao testar
contra um schema real multi-escopo): sem o escopo de destino, uma FK que
aponta pra uma tabela em **outro** escopo perdia essa informação — o modelo
só guardava o nome da tabela, nunca em qual escopo ela estava, deixando a
referência ambígua (ou errada) quando dois escopos tinham tabela com o
mesmo nome.

**Lista, não `Optional` único (issue #105):** uma coluna pode ter 2+
constraints FK de coluna única distintas apontando pra tabelas diferentes —
FK polimórfica sem discriminator, modelagem rara mas válida no motor.
Evidência real: MariaDB gerenciado com 843 tabelas, 3 colunas em produção
com esse padrão (achado durante o teste pós-implementação da #104). Antes
da #105, `construir_colunas_fk` mantinha só a última referência lida e
descartava as demais com `Aviso`; agora nenhuma é descartada — a lista
guarda todas, na ordem em que a query de catálogo do Extrator concreto as
retorna (ambas ordenam por `constraint_name`, garantindo ordem
determinística entre execuções sem trabalho extra). Diferente de FK
composta (`RestricaoDeFkComposta`, issue #95, ver abaixo): lá é **1**
constraint com 2+ colunas; aqui são **2+** constraints distintas de coluna
única na mesma coluna — os dois mecanismos convivem sem conflito.

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
    restricoes_unicas: list[RestricaoUnica] = Field(default_factory=list)
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(default_factory=list)
```

**Comportamento:** `amostra` é sempre preenchida pelo Extrator e obrigatória —
`TabelaExtraida` nunca chega ao Analisador (que só opera sobre `TabelaCurada`
via `ContextoDeAnalise.curado`), então não há estado intermediário em que ela
possa estar ausente aqui. Produzida pelo Extrator, consumida pela Sobrescrita.
O campo opcional (`pl.DataFrame | None`) e o descarte por liberação de memória
vivem em `TabelaCurada`, não em `TabelaExtraida` (ver seção Curation Context).

**`restricoes_unicas` (issue #89):** UNIQUE composto (2+ colunas) real do
schema — fato de catálogo, no mesmo nível epistemológico de
`nao_nulavel`/`unica` (#44), por isso campo direto de nível **tabela** (não
`MetricaDeTabela`). `unica: bool` em `ColunaExtraida` continua representando
só UNIQUE single-column; uma constraint composta não marca nenhuma coluna
individual. `RestricaoUnica` (`domain/model/common/restricao_unica.py`) é um
Value Object novo — `colunas: tuple[str, ...]`, `frozen=True`, mesmo padrão
de `ReferenciaDeColuna`, com validação de mínimo 2 colunas sem duplicata.
`TabelaExtraida` valida adicionalmente que toda coluna citada em
`restricoes_unicas` existe em `self.colunas` — pega bug de JOIN incorreto no
Extrator antes do hash estrutural ou da geração dbt. Propaga para
`TabelaCurada`/`TabelaAnalisada` automaticamente via `model_dump`/
`model_validate` (mesmo mecanismo de `iniciar_contexto`, ver Analysis
Context abaixo), sem exigir mudança em nenhum dos dois pontos de tradução.

**`restricoes_fk_compostas` (issue #95):** FK composta (2+ colunas locais
apontando pra 2+ colunas de uma mesma tabela referenciada) real do
schema — mesmo nível epistemológico de `restricoes_unicas`, por isso
também campo direto de nível **tabela**. `ColunaExtraida.referencias`
(per-coluna) **fica inalterado** e continua populado normalmente pra
toda coluna FK, inclusive as que fazem parte de uma constraint
composta — `RestricaoDeFkComposta` só existe para o agrupamento que uma
`ReferenciaDeColuna` por coluna não consegue expressar.
`RestricaoDeFkComposta` (`domain/model/common/restricao_de_fk_composta.py`)
é um Value Object novo — `colunas_locais: tuple[str, ...]`,
`nome_escopo_referenciado: str`, `nome_tabela_referenciada: str`,
`colunas_referenciadas: tuple[str, ...]`, `frozen=True`, mesmo padrão de
`RestricaoUnica`, validado (mínimo 2 colunas locais sem duplicata,
mesmo número de colunas locais e referenciadas). `TabelaExtraida` valida
adicionalmente que toda coluna local citada em `restricoes_fk_compostas`
existe em `self.colunas` (mesmo padrão do validator de
`restricoes_unicas`). Propaga para `TabelaCurada`/`TabelaAnalisada` da
mesma forma automática, sem exigir mudança em `_traduzir`/
`iniciar_contexto`.

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
    referencias: list[ReferenciaDeColuna] = Field(default_factory=list)
    nao_nulavel: bool = False  # NOT NULL real do schema (issue #44)
    unica: bool = False        # UNIQUE single-column real do schema (issue #44)
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
    restricoes_unicas: list[RestricaoUnica] = Field(default_factory=list)
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(default_factory=list)
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
    percentual_nulo: float                       # 0.0–100.0
    percentual_unico: float                      # 0.0–100.0, nulos excluídos do numerador
    valores_frequentes: list[tuple[str, int]]     # até 10 pares (valor, contagem), nulos excluídos
    minimo: str | None                            # representação string do mínimo
    maximo: str | None                            # representação string do máximo
    formato_detectado: str | None                # "email", "cpf", "cnpj", "phone", "cep"
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
    referencias: list[ReferenciaDeColuna]
    nao_nulavel: bool  # NOT NULL real do schema (issue #44)
    unica: bool         # UNIQUE single-column real do schema (issue #44)
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
    restricoes_unicas: list[RestricaoUnica] = Field(default_factory=list)
    restricoes_fk_compostas: list[RestricaoDeFkComposta] = Field(default_factory=list)
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

**Boundary de exceção (issue #56):** cada `estagio(valor)` roda dentro de
`executar_com_seguranca` (`pipeline/seguranca.py`) — uma `Exception` não
prevista de qualquer Estagio vira `Falha` (nome do Estagio + tipo da
exceção na mensagem), nunca propaga crua. Ver Decisão 12 do
`system_design_doc.md`.

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

**`ExtratorRegistrado` (issue #67)** — dataclass frozen, também em
`domain/ports/extrator.py` e reexportada em `domain/ports/__init__.py`:

```python
@dataclass(frozen=True)
class ExtratorRegistrado:
    classe_extrator: type[Extrator]
    construir: Callable[[ConfiguracaoDeExtracao], Extrator]
```

É o alvo do entry point do grupo `ddf.extratores` (`cli/registro/descoberta.py`)
— um plugin de terceiro expõe uma instância pronta deste tipo, não só a
classe do Extrator, porque o construtor de um Extrator concreto
normalmente precisa perguntar credenciais/parâmetros específicos da fonte
de forma interativa (`construir` encapsula isso). Faz parte do contrato
público versionado junto de `Extrator` (ver seção de versionamento
semântico em `docs/engineer_guidelines.md`) — não é um detalhe interno de
CLI, mesmo sendo consumido primeiro por `cli/registro/extratores.py`.

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
        /,
    ) -> Resultado[ContextoDeAnalise]: ...
    # parâmetro positional-only (`/`) — mesmo motivo do Extrator: adapters
    # concretos podem usar outro nome internamente sem quebrar em runtime
    # uma chamada por keyword feita contra o tipo Analisador
```

**Comportamento esperado:**
- Lê `entrada.curado` para acessar os DataFrames via Polars.
- Lê `entrada.analisado` para acessar métricas de Analisadores anteriores.
- Devolve um `ContextoDeAnalise` **novo**, nunca muta `entrada` (Decisão 11
  do `system_design_doc.md`, revisão pré-CLI/issue #53) — o `analisado`
  desse novo contexto acrescenta Value Objects do seu tipo à lista
  `metricas` de cada `ColunaAnalisada`/`TabelaAnalisada`, sem sobrescrever
  métricas existentes; o `curado` desse novo contexto tem
  `tabela_curada.amostra = None` após processar cada tabela — libera memória
  sem quebrar o tipo (`amostra: pl.DataFrame | None`).
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
        /,
    ) -> Resultado[None]: ...
    # parâmetro positional-only (`/`) — mesmo motivo do Extrator/Analisador
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
        progresso: Callable[[str], None] | None = None,
        ao_conhecer_total: Callable[[int], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        progresso: Callable[[str], None] | None = None,
    ) -> Resultado[BancoCurado]: ...
```

**Comportamento esperado de `extrair`:**
- Lista tabelas via `extrator.listar_tabelas()` para cada escopo.
- Distribui `extrair_tabela()` em workers paralelos.
- **Sucesso parcial (issue #16):** falha ao listar um escopo ou extrair uma
  tabela nunca aborta o lote inteiro — vira `Aviso` no `Sucesso` devolvido,
  junto das tabelas que deram certo. O método nunca devolve `Falha`; o
  chamador decide o que fazer com uma lista vazia (ver `wizard.py`, que sai
  com código 1 se nenhuma tabela foi extraída).
- `progresso`, se informado, é chamado uma vez por item concluído (sucesso
  ou falha) com o identificador `"<escopo>.<tabela>"` — alimenta a barra de
  progresso do wizard sem acoplar o Port a `questionary`.
- `ao_conhecer_total`, se informado, é chamado uma única vez, logo após a
  listagem interna terminar e antes da extração paralela começar, com o nº
  de pares a extrair — elimina a necessidade do chamador listar as tabelas
  de novo por fora só para saber o total (issue #75; antes `cli/etapas/
  extracao.py` tinha um `_contar_tabelas` que duplicava essa listagem).

**Comportamento esperado de `aplicar_sobrescritas`:**
- Distribui `sobrescrita()` em workers paralelos sobre a lista recebida.
- Agrega `list[TabelaCurada]` em `BancoCurado` após todos terminarem.
- Mesma política de sucesso parcial e `progresso` de `extrair`.

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
    def requisicao(self) -> RequisicaoDeAmostragem: ...
    """O que amostrar — cada Extrator decide como, no dialeto próprio."""
```

```python
class AmostragemProbabilistica(BaseModel):  # frozen
    percentual: float  # (0, 100]
    seed: int | None = None

class AmostragemIntegral(BaseModel):  # frozen, sem campos
    ...

RequisicaoDeAmostragem = AmostragemProbabilistica | AmostragemIntegral
```

**Comportamento:** descreve só a *política* de amostragem (quanto amostrar),
nunca gera SQL. Traduzir isso numa consulta concreta é responsabilidade de
cada `Extrator` — que já é, por definição, acoplado ao dialeto da própria
fonte de dados. Isso evita que `EstrategiaDeAmostragem` (um Port pensado para
ser agnóstico de fonte, com fontes futuras como MariaDB/API/arquivo) precise
de uma implementação nova por banco só para gerar SQL diferente — o mesmo
`PercentualDeLinhas(percentual=5.0)` serve para qualquer `Extrator`, cada um
decidindo como aplicá-lo no próprio dialeto.

**`requisicao: RequisicaoDeAmostragem` em vez de `percentual: float` solto
(issue #76, reabertura desta decisão):** a v1 do Port expunha `percentual`
diretamente — funcionava com uma única estratégia, mas ao introduzir
`TabelaInteira` (que não tem percentual nenhum) isso forçaria a nova estratégia a
"mentir" um valor fictício só para satisfazer o Protocol, violando
Interface Segregation. `RequisicaoDeAmostragem` é uma união fechada
(`AmostragemProbabilistica | AmostragemIntegral`); cada `Extrator` faz
`match`/`assert_never` sobre ela — uma estratégia futura não reconhecida
quebra `mypy --strict` no Extrator, em vez de cair silenciosamente num
`else` que trata tudo como probabilístico. `seed` vive só em
`AmostragemProbabilistica` (nunca no Port nem em `AmostragemIntegral`, que
não tem o que reproduzir) — torna a amostragem reprodutível via
`REPEATABLE`/`RAND(seed)` de cada dialeto.

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
        connect_timeout: int = 50,
    ) -> None: ...
```

**Construção:** cria `ThreadedConnectionPool(minconn=1, maxconn=max_conexoes,
dsn=dsn, connect_timeout=connect_timeout)` e um `threading.Semaphore(max_conexoes)`
interno. `max_conexoes` é parâmetro próprio de `ExtratorPostgres` (não vem de
`ConfiguracaoDeExtracao`, que não carrega mais nenhum conceito de
concorrência desde a issue #10) — conhecimento específico de quanto este
Postgres aguenta com segurança, default `8`.

**`connect_timeout` (issue #75):** sem esse parâmetro, um host inacessível
por firewall (pacote descartado, não recusado) trava a conexão TCP inicial
por um timeout do SO que pode passar de um minuto — o libpq não tem
timeout de conexão por padrão. Default `50` segundos, pago uma única vez no
aquecimento do pool (`minconn=1`), não por query. Não exposto no wizard —
`_construir_extrator_postgres` usa o default, mesmo padrão de
`max_conexoes`. `ExtratorMariaDB` ganhou o parâmetro homônimo por simetria
de leitura do código (`connect_timeout: int = 10`, repassado ao
`PooledDB`) — o `pymysql` já tinha esse valor como default implícito do
próprio driver, então declarar explicitamente não muda o comportamento,
só deixa de depender de conhecer o driver pra saber o timeout real.

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
   + `key_column_usage` para PK; para o destino de cada FK, `key_column_usage`
   (colunas locais) + `referential_constraints` + uma segunda leitura de
   `key_column_usage` (colunas referenciadas), casando
   `kcu.position_in_unique_constraint = ccu.ordinal_position` — inclui
   `ccu.table_schema` além de `ccu.table_name`/`ccu.column_name`, pra
   `ReferenciaDeColuna` capturar FK que aponta pra outro escopo). **Reabertura
   de escopo da #9 (achada na revisão da #35):** a versão original casava
   `table_constraints`/`constraint_column_usage` só por `constraint_name`, sem
   usar posição — pra FK composta (2+ colunas), isso gera produto cartesiano
   das colunas locais × colunas referenciadas (ex.: FK de 2 colunas retornava
   4 linhas em vez de 2, com pareamento coluna-local↔coluna-referenciada
   potencialmente trocado). Validado empiricamente contra Postgres 16 real
   antes e depois do fix. `MariaDB` nunca teve esse problema —
   `key_column_usage` já traz `REFERENCED_COLUMN_NAME` pareado corretamente
   por linha via `ORDINAL_POSITION`/`POSITION_IN_UNIQUE_CONSTRAINT`, sem
   precisar de um segundo JOIN. **Issue #44:** a mesma leitura de
   `information_schema.columns` passa a incluir `is_nullable` (sem JOIN
   novo) para `nao_nulavel`. UNIQUE (`unica`/`restricoes_unicas`) é lido à
   parte, via catálogo `pg_index` (não `information_schema.
   table_constraints`, desvio deliberado do padrão de PK/FK): todo UNIQUE
   constraint no Postgres é backed por um índice em `pg_index`, então uma
   única query cobre tanto constraint UNIQUE nomeada quanto `CREATE UNIQUE
   INDEX` solto (sem `ADD CONSTRAINT`) — o segundo caso não aparece em
   `information_schema.table_constraints` de jeito nenhum. `NOT
   i.indisprimary` exclui PK sem lógica extra (o índice de suporte de uma PK
   nunca aparece como uma entrada `indisunique` "solta").

   **Issue #89:** a versão original desta query filtrava
   `array_length(i.indkey, 1) = 1`, descartando UNIQUE composto (2+
   colunas) de propósito — só existia `unica: bool` single-column então. A
   versão atual usa `unnest(i.indkey) WITH ORDINALITY` para desempacotar
   todas as colunas de cada índice, cobrindo single-column e composto numa
   passada só, agrupadas depois em Python por `(nome_tabela, indexrelid)`
   — grupo de 1 vira `unica`, grupo de 2+ vira `RestricaoUnica`. 4
   predicados adicionais (achados da banca de revisão, validados
   empiricamente contra Postgres 16 real) evitam índices que a versão
   antiga descartava só por acidente: `indexprs IS NULL` (índice de
   expressão, ex. `UNIQUE(b, lower(a))` — o JOIN de `attnum` falha pra
   entrada de expressão, sobrando só as colunas reais e classificando-as
   erradamente), `k.ord <= i.indnkeyatts` (exclui coluna `INCLUDE` de
   índice covering, PG11+), `indpred IS NULL` (exclui índice UNIQUE
   parcial — ex. soft-delete — que não garante unicidade da tabela
   inteira) e `indisvalid` (exclui índice inválido, ex. `CONCURRENTLY` que
   falhou):
   ```sql
   SELECT t.relname, i.indexrelid, a.attname
   FROM pg_index i
   JOIN pg_class t ON t.oid = i.indrelid
   JOIN pg_namespace n ON n.oid = t.relnamespace
   JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
   JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
   WHERE i.indisunique AND NOT i.indisprimary
     AND i.indexprs IS NULL AND i.indpred IS NULL AND i.indisvalid
     AND k.ord <= i.indnkeyatts
     AND n.nspname = %s
   ORDER BY t.relname, i.indexrelid, k.ord
   ```

   **`restricoes_fk_compostas` (issue #95):** a query de FK (item 1 acima)
   já lia `constraint_name` internamente pro JOIN, mas não o expunha no
   `SELECT` — passa a incluir `tc.constraint_name` e `kcu.ordinal_position`,
   com `ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position`
   (mesmo achado de estabilidade da #89 pro hash estrutural). Novo helper
   agnóstico de fonte `construir_restricoes_fk_compostas`
   (`extractors/comum/construir_restricoes_fk_compostas.py`, mesmo padrão de
   `construir_colunas_fk`) agrupa as linhas por `constraint_name`: grupo de
   1 continua indo só para o dict `colunas_fk` existente via
   `construir_colunas_fk` (comportamento inalterado); grupo de 2+ também
   vira uma `RestricaoDeFkComposta`. Achado do Arquiteto na banca de
   revisão do plano: se `colunas_referenciadas` de um grupo não corresponde
   a nenhuma PK/UNIQUE (single ou composto) conhecida do lado referenciado
   — banco legado malformado, raro mas real — `OrquestradorParalelo.
   extrair` emite `Aviso` explícito (checagem cross-table, só possível
   depois que todas as tabelas do escopo foram extraídas; ver seção do
   `OrquestradorParalelo` abaixo), em vez de confiar na `RestricaoDeFkComposta`
   silenciosamente.

   **`construir_colunas_fk` (issue #105, reabertura de escopo):** antes,
   quando uma coluna tinha 2+ constraints FK de coluna única distintas
   (grupo de 1 dentro de `construir_restricoes_fk_compostas`, mas
   múltiplos grupos de 1 pra mesma coluna — FK polimórfica sem
   discriminator), `construir_colunas_fk` mantinha só a última referência
   lida e emitia `Aviso` pela perda das demais. Passa a agrupar por
   coluna sem descartar nada: retorna `dict[str, list[ReferenciaDeColuna]]`
   (antes `dict[str, ReferenciaDeColuna]`), sem `Aviso`/parâmetro `origem`
   (nada mais é perdido, então não há mais o que avisar).
   `ColunaExtraida.referencias`/`ColunaCurada.referencias`/
   `ColunaAnalisada.referencias` acompanham a mudança (ver seções dos
   3 Contexts acima). Evidência real: MariaDB gerenciado com 843 tabelas,
   3 colunas em produção com esse padrão (achado durante o teste
   pós-implementação da #104).
2. Mapeia tipos Postgres → `TipoDeDado` (tabela abaixo).
3. Lê `total_linhas` via `COALESCE(NULLIF(n_live_tup, 0), CASE WHEN relkind
   <> 'p' AND pg_relation_size(oid) = 0 THEN 0 ELSE NULLIF(reltuples, -1)
   END, 0)` — **estimativa de catálogo**, não `COUNT(*)` exato (`COUNT(*)`
   exigiria um segundo full-scan além do já pago pela amostragem — issue
   #76, avaliação do engenheiro-de-dados). `n_live_tup` é contador
   incremental por churn de DML, mais atual que `reltuples` (que só muda no
   `ANALYZE`) — trocado nesta issue. `NULLIF(n_live_tup, 0)` trata "0 sem
   estatística reportada ainda" (tabela recém-carregada sem `ANALYZE`) como
   ausência, não zero real — validado contra Postgres real via
   `testcontainers`; a janela observada foi `INSERT` sem `ANALYZE`, não
   pós-`ANALYZE` (`ANALYZE` força flush síncrono das próprias stats, então
   não reproduz "`n_live_tup` desatualizado logo após `ANALYZE`" — suspeita
   inicial, refutada na validação empírica). O `CASE` cobre o que o
   `NULLIF` sozinho não cobre e que `reltuples` também erra: `TRUNCATE`
   zera `n_live_tup` mas deixa `reltuples` com o valor antigo
   indefinidamente (sem gatilho de autovacuum depois de `TRUNCATE`).
   `pg_relation_size(oid) = 0` é sinal físico direto (arquivo de dados
   vazio); `relkind <> 'p'` exclui tabela-mãe particionada, que sempre tem
   tamanho 0 por não ter storage próprio. **Limitação aceita, não
   resolvida:** `DELETE` em massa sem `TRUNCATE`, antes do autovacuum
   truncar as páginas vazias, ainda pode reportar total desatualizado —
   sem sinal de catálogo barato pra esse caso específico.
4. Monta e executa a query de amostra a partir de
   `configuracao.estrategia_obrigatoria().valor.requisicao` (`Falha` cedo se
   `estrategia` ainda `None`, issue #75; `match`/`assert_never` sobre a
   requisição, issue #76):
   - `AmostragemProbabilistica(percentual, seed)`: `SELECT * FROM
     {schema}.{tabela} TABLESAMPLE BERNOULLI(percentual) REPEATABLE(seed)`.
     `BERNOULLI` sorteia cada linha independentemente com probabilidade
     igual — amostra estatisticamente não enviesada, ao contrário de
     `LIMIT` sem `ORDER BY` (que reflete a ordem física/de inserção da
     tabela) e mais barata que `ORDER BY random() LIMIT N` (não exige sort
     completo da tabela). `seed` nunca é omitido: se o usuário não informar
     um, o Extrator gera um (`seed_efetivo`) antes de montar a query, para
     reprodutibilidade nunca ser opt-in silencioso.
   - `AmostragemIntegral()`: `SELECT * FROM {schema}.{tabela}` puro, sem
     `TABLESAMPLE` — a estratégia `TabelaInteira`.
5. `MetadadosDeAmostra.tamanho_amostra` é o número de linhas efetivamente
   retornadas pela amostra (`len(dataframe)`), não um valor calculado —
   `TABLESAMPLE` decide dinamicamente quantas linhas sorteia.
   `construir_metadados_de_amostra` (helper compartilhado com
   `ExtratorMariaDB`, mesmo padrão de `construir_colunas_fk`) monta
   `MetadadosDeAmostra` e o `Aviso` de divergência (`tamanho_amostra >
   total_linhas`). Em `AmostragemIntegral`, `TabelaExtraida.total_linhas`
   vira `len(amostra)` em vez da estimativa de catálogo — exato por
   definição, já que a tabela inteira foi lida; o `Aviso` de divergência
   estruturalmente nunca dispara nesse caso.
6. Retorna `TabelaExtraida`.

**`ExtratorMariaDB` segue o mesmo dispatch**, com `WHERE RAND(seed) <=
percentual/100` no lugar de `TABLESAMPLE`/`REPEATABLE` (MariaDB não tem
`TABLESAMPLE`) e `SELECT * FROM {escopo}.{tabela}` puro em
`AmostragemIntegral`. `total_linhas` continua vindo de
`information_schema.tables.TABLE_ROWS`, sem mudança — MariaDB não tem fonte
equivalente a `n_live_tup` sem escrita (`ANALYZE TABLE`) ou full-scan
(`COUNT(*)`).

**`restricoes_unicas` no MariaDB (issue #89):** sem query nova — a mesma
`_COLUNAS_UNICAS_SQL` (que já agrupa por `constraint_name` desde a #44 para
achar UNIQUE single-column) agora também particiona os grupos de 2+ colunas
como `RestricaoUnica`, via `_particionar_colunas_unicas`. A query ganhou
`ORDER BY constraint_name, ordinal_position` — achado da banca de revisão:
sem ordem garantida, a sequência de colunas dentro de uma constraint
composta oscilaria entre execuções sem nenhuma mudança real de schema,
disparando falso positivo no hash estrutural (`SobrescritaDeTabela`).

**`restricoes_fk_compostas` no MariaDB (issue #95):** sem query nova — a
mesma `_CHAVES_ESTRANGEIRAS_SQL` (per-tabela, diferente do Postgres que lê
o schema inteiro de uma vez) ganhou `CONSTRAINT_NAME` no `SELECT` e
`ORDER BY constraint_name, ordinal_position`. `construir_restricoes_fk_compostas`
(mesmo helper compartilhado com o Postgres) agrupa as linhas já lidas —
zero query adicional.

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

**Mapeamento de tipos MariaDB** (`mapeamento_de_tipos.py::mapear_tipo_mariadb`):

| Tipo MariaDB (`information_schema.columns.data_type`) | `CategoriaDeDado` | Atributos extras |
|---|---|---|
| `varchar` | `VARCHAR` | `tamanho_maximo` |
| `char` | `CHAR` | `tamanho_fixo` |
| `tinytext`, `text`, `mediumtext`, `longtext` | `TEXT` | — |
| `decimal` | `NUMERIC` | `precisao`, `escala` |
| `tinyint`, `smallint`, `mediumint`, `int` | `INTEGER` | — |
| `bigint` | `BIGINT` | — |
| `float` | `FLOAT` | `com_precisao_dupla=False` |
| `double` | `FLOAT` | `com_precisao_dupla=True` |
| `datetime` | `TIMESTAMP` | `com_timezone=False` |
| `timestamp` | `TIMESTAMP` | `com_timezone=True` |
| `time` | `TIME` | — |
| `date` | `DATE` | — |
| `enum`, `set` | `ENUM`/`SET` | `valores_permitidos` (extraídos do `column_type`, ex.: `enum('ativo','inativo')`) |
| `uuid` | `UUID` | — |
| qualquer outro (inclui `json`) | `UNKNOWN`, salvo reclassificação abaixo | — |

Tipos fora da tabela caem em `UNKNOWN`, nunca levantam exceção.

**Detecção de coluna JSON via CHECK constraint:** MariaDB nunca reporta
`data_type = "json"`, mesmo para uma coluna `JSON` de verdade — ela aparece
como `LONGTEXT` com um `CHECK(json_valid(...))` implícito adicionado pelo
próprio servidor. `_extrair_coluna_json_valid` faz parsing por regex do
`CHECK_CLAUSE` (`information_schema.CHECK_CONSTRAINTS`) procurando o padrão
`json_valid(\`coluna\`)`. Como nome de constraint no MariaDB é escopado por
*tabela*, não por schema, e `CHECK_CONSTRAINTS` não expõe `TABLE_NAME` para
filtrar isso na query, a mesma consulta pode retornar `CHECK_CLAUSE` de uma
constraint de outra tabela do schema com nome coincidente —
`_colunas_json_de_check_clauses` descarta esse ruído cruzando o nome extraído
contra as colunas reais da tabela (lidas de `information_schema.columns`).

**Promoção TINYINT(1) → BOOLEAN pela amostra:** MariaDB não guarda em
catálogo nenhum a distinção entre `BOOLEAN` e `TINYINT(1)` — são o mesmo
tipo físico. `_promover_booleanos_pela_amostra` decide com base em dado
real: uma coluna `tinyint(1)` só é promovida a `BOOLEAN` se a amostra tiver
ao menos um valor não-nulo e todos os valores não-nulos forem `0`/`1`.
Amostra vazia ou só nulos não promove — falta de evidência não é evidência
de booleano, a coluna permanece `INTEGER`.

### `PercentualDeLinhas`

```python
class PercentualDeLinhas:
    def __init__(self, percentual: float, seed: int | None = None) -> None: ...
    # ValidationError (via AmostragemProbabilistica) se percentual não
    # estiver em (0, 100]

    @property
    def nome(self) -> str:
        """Retorna 'percentual_de_linhas'."""

    @property
    def requisicao(self) -> AmostragemProbabilistica:
        """Retorna percentual e seed configurados, como AmostragemProbabilistica."""
```

**Comportamento:** puramente uma política — não sabe nada de SQL nem do
banco de origem. Só guarda `percentual`/`seed` configurados (validados por
`AmostragemProbabilistica`, um `BaseModel` — a validação migrou do
`__init__` pra lá na issue #76, fonte única da regra); é o `ExtratorPostgres`
(ou qualquer `Extrator` futuro) quem decide como aplicá-los.

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

### `TabelaInteira` (issue #76)

```python
class TabelaInteira:
    """Sem parâmetros — não há o que configurar."""

    @property
    def nome(self) -> str:
        """Retorna 'tabela_inteira'."""

    @property
    def requisicao(self) -> AmostragemIntegral:
        """Retorna AmostragemIntegral()."""
```

**Comportamento:** lê a tabela inteira, sem `TABLESAMPLE`/`RAND()`. Resultado
prático equivalente a `PercentualDeLinhas(percentual=100)` (`BERNOULLI(100)`/
`RAND() <= 1` incluem cada linha com probabilidade 1), mas `TabelaInteira` deixa a
intenção explícita no artefato gerado (`metadados_amostra.estrategia ==
"tabela_inteira"`), e `TabelaExtraida.total_linhas` sai exato
(`len(amostra)`) em vez de estimativa de catálogo — sem o `Aviso` de
divergência que soava confuso especificamente nesse caso (motivação original
da issue #76). Zero mudança nos dois Extratores foi necessária para
adicionar esta estratégia: o vocabulário (`AmostragemIntegral`) já existia
no Port desde a mesma issue — prova prática do ponto de Open/Closed
perseguido no redesenho de `EstrategiaDeAmostragem`.

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
   col.nao_nulavel, col.unica,
   "|".join(r.model_dump_json() for r in col.referencias)) for col
   in colunas])` — `model_dump_json()` porque `TipoDeDado`/`ReferenciaDeColuna`
   são `BaseModel`, não primitivos hasheáveis diretamente; inclui o destino
   completo de **todas** as FKs da coluna (escopo + tabela + coluna cada,
   issue #10 reabre o hash original da #7/#8 introduzindo
   `ReferenciaDeColuna` pra incluir o escopo de destino, corrigindo perda de
   informação em FK cross-escopo; issue #105 generaliza de valor único pra
   lista, sem isso uma 2ª/3ª FK adicionada ou removida na mesma coluna não
   dispararia aviso de estrutura alterada) pra detectar mudança de
   referência mesmo quando `chave_estrangeira` continua `True`.
   `nao_nulavel`/`unica` entraram no hash na issue #44 —
   sem eles, uma coluna que virasse NOT NULL/UNIQUE no banco não disparava
   aviso de mudança estrutural nem regeneração do skeleton. `restricoes_unicas`
   (nível tabela) entra no hash na issue #89, uma parte
   `"restricao_unica:" + ",".join(colunas)` por `RestricaoUnica` — mesmo
   motivo, aplicado ao caso de UNIQUE composto. `restricoes_fk_compostas`
   entra no hash na issue #95, mesmo motivo aplicado à FK composta — uma
   parte `"restricao_fk_composta:" + colunas_locais + "->" + escopo_ref +
   "." + tabela_ref + ":" + colunas_referenciadas` por
   `RestricaoDeFkComposta`.
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
        /,
        progresso: Callable[[str], None] | None = None,
        ao_conhecer_total: Callable[[int], None] | None = None,
    ) -> Resultado[list[TabelaExtraida]]: ...

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
        progresso: Callable[[str], None] | None = None,
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
   de um escopo vira `Aviso`, não aborta os demais escopos.
2. Distribui `extrair_tabela(escopo, tabela)` em `ThreadPoolExecutor(max_trabalhadores)`
   para todos os pares `(escopo, tabela)` listados com sucesso.
3. **Sucesso parcial (issue #16):** cada falha — de listagem ou de extração —
   vira um `Aviso` (`"Falha ao extrair '<escopo.tabela>': <erro>"`), nunca
   aborta o lote. O método sempre devolve `Sucesso`, mesmo que nenhuma
   tabela tenha sido extraída (lista vazia) — o chamador decide o que fazer
   com isso.
4. `Sucesso` com `list[TabelaExtraida]` ordenada por `(nome_escopo,
   nome_tabela)` (`ThreadPoolExecutor` não garante ordem de conclusão) e os
   `Aviso`s acumulados.
5. `progresso`, se informado, é chamado a partir da thread principal (via
   `as_completed`) uma vez por item concluído — nunca dentro de um worker,
   por isso dispensa lock.
6. **`restricoes_fk_compostas` sem chave candidata (issue #95):** depois que
   todas as tabelas do lote já foram extraídas (única etapa em que
   `OrquestradorParalelo` enxerga o lote inteiro, não uma tabela por vez),
   `_avisos_de_fk_composta_sem_chave_candidata` compara `colunas_referenciadas`
   de cada `RestricaoDeFkComposta` contra os grupos de chave candidata
   (PK, UNIQUE single-column, UNIQUE composto) da tabela referenciada — só
   quando ela está no lote; fora do lote, sem visibilidade, nenhum `Aviso`
   (mesma regra do `relationships` single-column do `GeradorDbt`). Sinaliza
   banco legado malformado sem abortar a extração.

**Comportamento de `aplicar_sobrescritas`:**
1. Distribui `sobrescrita(tabela)` em `ThreadPoolExecutor(max_trabalhadores)`.
2. Mesma política de sucesso parcial de `extrair`: cada falha vira `Aviso`
   (`"Falha ao aplicar sobrescrita em '<escopo.tabela>': <erro>"`), nunca
   aborta o lote — `Sucesso` sempre, com `BancoCurado` cujas `tabelas` estão
   ordenadas por `(nome_escopo, nome_tabela)`.
3. `Aviso`s emitidos pela própria `Sobrescrita` em caminho de sucesso (ex.:
   `SobrescritaDeTabela` avisando que criou um skeleton) são preservados —
   não descartados por engano junto com o valor.

**Boundary de exceção (issue #56):** a chamada de `funcao(item)` dentro de
cada worker do `ThreadPoolExecutor` (`_executar_em_paralelo`) roda dentro
de `executar_com_seguranca` — uma `Exception` não prevista dentro de um
`Extrator`/`Sobrescrita` concreto vira uma falha isolada (mesma política de
acumulação já descrita acima), em vez de propagar crua via
`futuro.result()` e quebrar o lote inteiro. Ver Decisão 12 do
`system_design_doc.md`.

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
| `percentual_unico` | `col.drop_nulls().n_unique() / tamanho_amostra * 100` — nulos excluídos do numerador, `tamanho_amostra` (total, com nulos) no denominador, pra não inflar unicidade de colunas majoritariamente nulas |
| `minimo` | `str(col.min())` — `None` se coluna inteiramente nula |
| `maximo` | `str(col.max())` — `None` se coluna inteiramente nula |
| `valores_frequentes` | `col.drop_nulls().value_counts()`, top 10 por `(count desc, valor asc)` — desempate determinístico —, devolvidos como `(str, int)` |
| `formato_detectado` | regex sobre valores não-nulos (ver abaixo) |

`tamanho_amostra == 0`: todas as métricas acima retornam `0.0`/`None`/`[]` sem
tentar dividir — guarda explícita antes de qualquer cálculo, não decisão do
implementador.

**Normalização de dtype não-nativo antes do cálculo:** duas famílias de
dtype Polars quebram `min()`/`max()` com `InvalidOperationError` (ver
Decisão 12 do `system_design_doc.md`) — `pl.Object` (fallback do Polars pra
tipo Python sem mapeamento nativo, ex. `uuid.UUID` de uma coluna UUID do
MariaDB) e `pl.List` (dtype de uma coluna `ARRAY` do Postgres, ex.
`text[]`). `_normalizar_serie_nao_nativa` stringifica esses dois dtypes pra
Utf8 antes de qualquer cálculo, restaurando as operações que uma coluna
Utf8 comum já suporta (`n_unique()`/`value_counts()` funcionam nos dtypes
originais sem essa etapa — só min/max quebram). A conversão usa
`_representar_valor_nao_nativo`, não `str()` puro: dado binário
(`bytes`/`bytearray`/`memoryview` — `psycopg2` devolve `memoryview` pra
colunas `bytea`) viraria um endereço de memória (`<memory at 0x7f...>`) com
`str()` direto, então vira `"[dado binário, N bytes]"` em vez disso;
qualquer outro tipo usa `str()` normalmente.

**Detecção de formato** (só em `VARCHAR`/`TEXT`; threshold ≥ 80% dos
não-nulos **e** mínimo absoluto de 20 valores não-nulos — evita "falsa
confiança" em colunas com poucos valores presentes, ex. 3 de 3 batendo
100%). Regexes assumem contexto Brasil (CPF/CNPJ/CEP/DDD nacional) — decisão
de produto intencional para o caso de uso principal do ddf, não cobertura
internacional:

| Formato | Regex |
|---|---|
| `email` | `r'^[\w.+-]+@[\w.-]+\.[a-z]{2,}$'` (flags `re.IGNORECASE`) — aceita subdomínio/TLD composto (`user@mail.empresa.com.br`) |
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
de rodapé com `MetadadosDeAmostra` (estratégia, `percentual`/`seed` efetivos
quando presentes — issue #76 —, N amostrado, M total).

**NOT NULL/UNIQUE reais do schema (issue #44):** a coluna "Chave" da tabela
de Colunas virou **"Restrição"** e passou a acumular `PK`, `FK → ...`,
`UNIQUE` e `NOT NULL` — antes só PK/FK apareciam ali, deixando `nao_nulavel`/
`unica` visíveis só dentro do texto de Qualidade dos dados. `UNIQUE`/
`NOT NULL` são suprimidos quando a coluna já é PK (PK implica os dois,
marcar seria redundante). Na tabela de Qualidade dos dados,
`percentual_nulo` mostra `"0.00% (garantido pelo schema)"` quando
`coluna.nao_nulavel` — combina o fato estrutural (`ColunaAnalisada.
nao_nulavel`, do catálogo) com a métrica amostral (`MetricasBaseColuna.
percentual_nulo`) só na camada de apresentação, sem criar campo novo em
`MetricasBaseColuna`. O aviso de baixo sinal analítico em "Valores
frequentes por coluna" (já existente para PK) passa a valer também para
`unica=True`, com texto próprio — PK tem precedência quando as duas são
verdadeiras, sem duplicar o aviso. Quando **nenhuma** coluna é elegível pra
essa seção (ex.: amostra vazia — tabela sem linhas extraídas, caso comum o
suficiente pra aparecer num teste manual real), o cabeçalho "## Valores
frequentes por coluna" continua sendo renderizado com uma nota explicando o
motivo, em vez de a seção inteira desaparecer em silêncio (parecia bug de
geração, não fato sobre o dado — achado do usuário testando contra artefato
real, mesma categoria de correção já feita na #13 pra coluna 100% nula).
`CategoriaDeDado.JSON` entrou em `_CATEGORIAS_SEM_MINIMO_E_MAXIMO` na mesma
issue (bugfix trivial, não relacionado: mesma classe de bug de comparação
lexicográfica já corrigida pras demais categorias textuais/estruturadas).

**FK composta (issue #95):** bullet **"Chaves estrangeiras compostas"** em
"Fatos extraídos", análogo a "Restrições UNIQUE compostas" — formata cada
`RestricaoDeFkComposta` como `(colunas_locais) → escopo.tabela
(colunas_referenciadas)`, grupos ordenados por `colunas_locais`
(determinismo entre reextrações). Na tabela de Colunas, marcador
`"FK (composta)"` sinaliza participação, **sem substituir** o marcador
`"FK → escopo.tabela.coluna"` individual — a coluna continua mostrando sua
própria referência (`ColunaAnalisada.referencias` fica inalterado para FK
composta) mais o sinal de que ela participa de um grupo. Diferente de
`"UNIQUE (composto)"`, **não** é suprimido quando a coluna é PK — uma
coluna pode legitimamente ser PK e parte de uma FK composta ao mesmo tempo
(ex.: tabela de junção), diferente de UNIQUE onde PK já implica
unicidade.

**FK polimórfica (issue #105):** coluna com 2+ referências em
`ColunaAnalisada.referencias` mostra um marcador `"FK → escopo.tabela.
coluna"` por referência (mesmo separador por vírgula já usado pelos
demais marcadores) — puramente documentacional, sem risco de falso
positivo (diferente do `GeradorDbt`, ver abaixo).

---

### `GeradorDbt`

```python
class GeradorDbt:
    requer: list[type] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

**Saída:** `dbt_project.yml`, `README.md` (issue #77) na raiz do projeto
gerado e, por escopo, uma subpasta autocontida em
`models/staging/<escopo>/`: `sources.yml`, `stg_<escopo>__<tabela>.sql` por
tabela, e `schema.yml` — convenção real dbt-labs pra staging multi-source
("as you add more source systems, create a subdirectory per source"),
substituindo o layout achatado original (`models/staging/sources.yml`
único pra todos os escopos). `packages.yml` é **condicional**: só escrito
quando há pelo menos um consumidor real de `dbt_utils` no lote — hoje dois
possíveis, `dbt_utils.unique_combination_of_columns` (`restricoes_unicas`,
issue #89) ou `dbt_utils.not_null_proportion` (teste soft de nulo, issue
#90) — sem nenhum dos dois, declarar a dependência seria decoração no
artefato gerado. Se uma execução anterior gerou `packages.yml` e nenhum
consumidor sobrou no lote atual, o Gerador remove o arquivo órfão
explicitamente. `macros/matches_format/` (3 arquivos) e
`macros/unique_percentage_at_least.sql` (issue #90, ver seção própria
abaixo) seguem o mesmo princípio de escrita condicional + remoção de
órfão.

**Nome do staging model (issue #14, desvio deliberado do `stg_<tabela>`
originalmente cogitado):** `stg_<nome_escopo>__<nome_tabela>` (duplo
underscore, convenção dbt-labs pra múltiplas fontes) — nomes de model são
globalmente únicos no grafo dbt, e `stg_<tabela>` sozinho colidiria se dois
escopos tiverem tabela de mesmo nome (ex.: `vendas.clientes` e
`rh.clientes`). Continua valendo com a reorganização em subpastas por
escopo da issue #77: a subpasta desambigua o *arquivo* no filesystem, mas
o *nome do model* precisa continuar único no grafo dbt independente de
onde o `.sql` mora — por isso, ao contrário do `GeradorContextoDeIA` (que
descartou o prefixo de escopo no nome do arquivo por não ter essa
restrição), o `GeradorDbt` mantém o prefixo.

**Nota de idioma:** esta é a única saída do sistema cujo destino consome os
nomes diretamente (o próprio dbt e o warehouse). Por isso, e só aqui, os
identificadores gerados no artefato (nomes de coluna/tabela em `schema.yml`,
`sources.yml` e no SQL, além do vocabulário de teste `unique`/`not_null`/
`relationships`/`accepted_values`) permanecem em **inglês**, refletindo o
contrato real consumido pelo dbt — não o código Python do `GeradorDbt`, que
segue a mesma convenção de nomenclatura em português dos demais
componentes.

**Testes sugeridos deterministicamente:**

| Condição | Teste |
|---|---|
| `percentual_unico == 100.0` **ou** `coluna.unica` | `unique` |
| `percentual_nulo == 0.0` **ou** `coluna.nao_nulavel` | `not_null` |
| `chave_estrangeira == True`, `len(referencias) == 1`, coluna **não** pertence a nenhuma FK composta **e** tabela referenciada presente no lote analisado | `relationships` → `ref()` do staging model referenciado |
| `chave_estrangeira == True`, `len(referencias) == 1` **e** tabela referenciada ausente do lote | sem teste + `Aviso` |
| `chave_estrangeira == True` **e** `len(referencias) >= 2` (FK polimórfica, issue #105) | sem teste + `Aviso` — ver nota abaixo |
| coluna pertence a alguma `RestricaoDeFkComposta` da tabela | `relationships` per-coluna **suprimido** — ver `composite_relationships` model-level abaixo (issue #95) |
| `_elegivel_para_enumeracao` aprova a coluna (ver critérios abaixo) | `accepted_values`, com `config: {severity: warn}` |

**FK polimórfica não recebe `relationships` automático (issue #105,
achado bloqueante da banca de revisão):** o teste `relationships` assume
"toda linha satisfaz esta relação". Para uma coluna com 2+ referências
(ex.: `entidade_id` que aponta ora pra `clientes` ora pra `fornecedores`,
sem coluna discriminadora), qualquer linha que aponte pra B falha o teste
escrito contra A — falso positivo garantido na maioria dos casos reais,
não cobertura extra. Precedente de mercado (dbt/DataHub/OpenMetadata): FK
ambígua é documentada, não testada automaticamente; um engenheiro com FK
polimórfica real escreve `relationships` manual com `where` filtrando
pelo discriminador. Por isso o `GeradorDbt` nunca escolhe uma referência
arbitrária pra testar — omite o teste e emite `Aviso` citando as N
referências. `GeradorMarkdown`/`GeradorContextoDeIA` continuam listando
todas normalmente (documentação, sem risco de falso positivo).

`unique`/`not_null` são suprimidos quando a coluna já é `chave_primaria`
(PK implica os dois). Combinar o fato estrutural do schema
(`unica`/`nao_nulavel`) com a métrica amostral — em vez de só a métrica,
como a issue original cogitava — resolve a pendência registrada pela #44:
sugerir teste só a partir de amostra tem o mesmo viés estatístico que
motivou aquela issue. `accepted_values` usa `severity: warn` porque é
enumeração exaustiva calculada sobre `valores_frequentes` (top-10
**amostral**, não a população completa) — um valor de cauda longa fora da
amostra não deve quebrar CI silenciosamente.

**Cinco critérios de elegibilidade — `_elegivel_para_enumeracao` (issue
#95):** rodando o wizard contra um banco de teste real, os critérios
originais (só `percentual_unico < 10.0` + cobertura) sugeriram
`accepted_values` para `criado_em` (TIMESTAMP travado em 2 valores
literais na amostra), `produto_codigo` (código de catálogo crescente,
`PRD-1..4` na amostra) e `quantidade` (INTEGER de baixa cardinalidade só
na amostra, alta variação esperada na população). `_elegivel_para_enumeracao`
(`generators/comum/_metricas.py`, compartilhada entre `GeradorDbt` e
`GeradorContextoDeIA`) combina, todos obrigatórios:

1. **Categoria não excluída** — `_CATEGORIAS_EXCLUIDAS_DE_ENUMERACAO =
   {TIMESTAMP, DATE, TIME, UUID, JSON, ARRAY}`: monotônicas por natureza
   (`TIMESTAMP`/`DATE`/`TIME` — nenhuma amostra torna um "criado em" um
   universo fechado), defesa barata (`UUID` — identidade, nunca categoria)
   ou semanticamente incompatíveis com enum (`JSON`/`ARRAY`).
   Deliberadamente **sem** `INTEGER`/`NUMERIC` em bloco —
   `quantidade`/`status_code`/`rating` podem ser categóricos reais; o
   problema desses é amostra pequena (critério 2), não o tipo.
2. **Piso de amostra** — `tamanho_amostra >= _TAMANHO_AMOSTRA_MINIMO_ENUMERACAO
   (100)`, mesmo valor do `Aviso` de baixo sinal do
   `AnalisadorDeMetricasDeColuna`. Antes desta issue, só o
   `GeradorContextoDeIA` tinha esse piso (`_TAMANHO_AMOSTRA_MINIMO_ENUM`,
   local); o `GeradorDbt` não tinha nenhum.
3. **Teto de cardinalidade real** — contagem de valores distintos
   reconstruída via `_contagem_de_distintos` (`percentual_unico` aplicado
   sobre os não-nulos da amostra inteira, **não** `len(valores_frequentes)`)
   menor que `_CARDINALIDADE_MAXIMA_ACCEPTED_VALUES (10)`.
   `valores_frequentes` é truncado em top-10 pelo Analisador, então contar
   o tamanho da lista não distingue "a coluna tem exatamente 10 distintos"
   de "tem 200 e só vemos os 10 mais frequentes"; a contagem reconstruída
   resolve essa ambiguidade sem campo novo em `MetricasBaseColuna`.
4. **`percentual_unico < 10.0`** — sinal de baixa cardinalidade relativa
   (critério original).
5. **Cobertura** — soma das contagens dos top-10
   (`_cobertura_dos_valores_frequentes`) cobre pelo menos 90% dos valores
   **não-nulos** de `MetadadosDeAmostra.tamanho_amostra` (critério
   original) — o denominador exclui os nulos porque `valores_frequentes`
   também é calculado só sobre não-nulos; dividir pelo total penalizaria
   injustamente uma coluna categórica com muitos nulos cujos valores
   presentes já são exaustivos. Cobertura baixa é sinal de que a lista está
   longe de ser exaustiva mesmo dentro do universo não-nulo amostrado.

Detectar um código de catálogo crescente disfarçado de categórico (ex.
`produto_codigo` com prefixo fixo + sufixo numérico) via parsing de
string foi avaliado e adiado — exigiria inferir a forma do dado, mais
próximo da heurística de análise automática que a Restrição 5 do PRD
veda nesta versão do que uma regra determinística simples; documentado
como limitação conhecida.

`relationships` aponta para
`ref()` (não `source()`) porque testa o dado já castado pelo staging, não o
bruto; só é gerado quando a tabela referenciada também foi analisada nesta
execução — apontar `ref()` para um model que este Gerador não produziu
quebraria `dbt run` do usuário.

**Teste model-level — `dbt_utils.unique_combination_of_columns` (issue
#89):** diferente da tabela acima (testes de **coluna**), este é o único
teste sugerido no nível do **model** (tabela) — um por `RestricaoUnica` de
`TabelaAnalisada.restricoes_unicas`, com `combination_of_columns` listando
as colunas na mesma ordem capturada do catálogo. Severidade **padrão**
(`error`, sem `config: {severity: warn}`), ao contrário de
`accepted_values`: é fato estrutural do schema (constraint UNIQUE real),
não estimativa sobre amostra — não há razão estatística para suavizar.
Requer `packages.yml` declarando `dbt-labs/dbt_utils` (ver "Saída" acima),
por isso só é sugerido quando `restricoes_unicas` não é vazio — o mesmo
UNIQUE composto que aciona a geração condicional de `packages.yml`.

**Teste model-level — `composite_relationships` (macro custom, issue
#95):** fecha a limitação conhecida desde a #56 — um por
`RestricaoDeFkComposta` de `TabelaAnalisada.restricoes_fk_compostas`, só
quando a tabela referenciada está no lote (`presentes`, mesma checagem do
`relationships` single-column; senão `Aviso` + omissão). Nem dbt-core nem
`dbt_utils` têm teste nativo de relationships multi-coluna — macro
genérica nova em `macros/composite_relationships.sql` (arquivo único, sem
subpasta nem dispatch por engine, ao contrário de `matches_format`: a
comparação é SQL ANSI puro, `NOT EXISTS` + igualdade por coluna, sem
depender de sintaxe de tupla/`ROW` específica de motor). Um CTE `child`
exclui linhas com qualquer coluna local `NULL` antes da comparação —
semântica `MATCH SIMPLE`, confirmada como comportamento correto e default
tanto em Postgres quanto em MariaDB/InnoDB pelo engenheiro-de-dados na
banca de revisão do plano (nenhuma engine de storage do MySQL/MariaDB
reconhece a cláusula `MATCH` — o efeito observado já é `MATCH SIMPLE`
sempre). Comparação por igualdade coluna-a-coluna via `NOT EXISTS`,
deliberadamente não por concatenação de string (`col_a || '|' || col_b`)
— alternativa de mercado avaliada e descartada: introduziria risco de
colisão de delimitador (dois pares logicamente distintos podem gerar a
mesma string concatenada sem um separador/encoding garantidamente seguro).
Severidade **padrão** (`error`), mesma decisão de
`unique_combination_of_columns` — fato estrutural, não amostral. Não
depende de `dbt_utils` (macro 100% autocontida), por isso não afeta
`_precisa_dbt_utils`/`packages.yml`; escrito/removido condicionalmente
via `_precisa_composite_relationships`, mesmo padrão de
`unique_percentage_at_least.sql`.

**Macros custom — `matches_format` e testes soft de nulo/unicidade (issue
#90):** adiada da #77 (junto da #89), fecha a lacuna de duas métricas já
calculadas por `AnalisadorDeMetricasDeColuna` mas nunca consumidas pelo
`GeradorDbt`: `formato_detectado` e a faixa intermediária de
`percentual_nulo`/`percentual_unico` entre "sem sinal" e o `unique`/
`not_null` hard da tabela acima.

| Condição | Teste |
|---|---|
| `formato_detectado` presente | `matches_format`, `config: {severity: warn}` |
| `0 < percentual_nulo <= 10.0` **e** `tamanho_amostra >= 100`, coluna não é PK nem `nao_nulavel` | `dbt_utils.not_null_proportion` (`at_least: 0.9`), `config: {severity: warn}` |
| `95.0 <= percentual_unico < 100.0` **e** `tamanho_amostra >= 100`, coluna não é PK nem `unica` | `unique_percentage_at_least` (`at_least: 0.95`), `config: {severity: warn}` |

*`matches_format` — dispatch por adapter, um arquivo por engine.*
`macros/matches_format/matches_format.sql` define o teste genérico e o
dict de patterns (cópia literal de `_REGEXES` em
`infrastructure/adapters/analyzers/comum/detector_de_formato.py`) e delega a
validação via `adapter.dispatch('validate_format', 'ddf_staging')`.
`postgres__validate_format.sql` (via `~*`) e `mariadb__validate_format.sql`
(via `REGEXP`) são arquivos **separados**, um por engine suportada — decisão
deliberada de não centralizar as implementações num único arquivo com
`if`/dispatch embutido: dar suporte a uma engine nova nesta v1 significa
literalmente criar `macros/matches_format/<adapter>__validate_format.sql`,
o ponto de extensão fica visível no filesystem. Engine sem implementação
cai em `default__validate_format`, que falha explícito via
`exceptions.raise_compiler_error` — nunca silenciosamente. `severity: warn`
por padrão porque o detector que gerou a sugestão já tolera até 20% de
não-match na amostra (`_THRESHOLD` em `detector_de_formato.py`); `error`
quebraria `dbt test` sistematicamente contra dado de produção real (CPF
mascarado, e-mail de sistema, telefone internacional). `~*` no Postgres (não
`~`) dá paridade com o `re.IGNORECASE` do regex fonte de email — MariaDB
`REGEXP` é case-insensitive por padrão só sob collation `_ci`, limitação
documentada no README do projeto gerado quando `matches_format` está em
uso. `set(_REGEXES.keys())` e as chaves embutidas no macro são duas fontes
de verdade mantidas manualmente em paralelo (Python vs. SQL estático) — um
teste de contrato em `tests/unit` compara as duas, porque um formato
adicionado só de um lado quebraria em `dbt compile`/`dbt test` do usuário
final, nunca no `pytest` do próprio ddf.

*Testes soft de nulo/unicidade — thresholds 10%/95%, não 5%/90%.* Perto do
piso de amostra (`_TAMANHO_AMOSTRA_MINIMO_SOFT = 100`, mesmo valor de
`_TAMANHO_AMOSTRA_MINIMO_AVISO` em `AnalisadorDeMetricasDeColuna`, mas
redefinido localmente — mesmo padrão do piso compartilhado
`_TAMANHO_AMOSTRA_MINIMO_ENUMERACAO` em `generators/comum/_metricas.py`, issue
#95), o erro padrão de uma
proporção é da mesma ordem de um threshold mais apertado: em N=100, o erro
padrão perto de p=0.05 é de ~2,2 pontos percentuais, e perto de p=0.90 é de
~3 pontos. Um threshold de 5%/90% faria a sugestão oscilar entre
reextrações por ruído de amostragem — não mudança real do dado — e isso
aparece como diff no `schema.yml` versionado que o curador revisa a cada
PR. 10%/95% ficam deliberadamente mais longe dessa fronteira ruidosa.
`dbt_utils.not_null_proportion` (dependência já presente no pacote) cobre o
caso de nulo, sem macro novo; unicidade não tem equivalente pronto no
`dbt_utils` (o `unique` builtin conta duplicatas, não proporção), por isso
usa o macro custom `unique_percentage_at_least.sql` — SQL ANSI puro
(`count(distinct ...) * 1.0 / count(...)`), sem dispatch por adapter porque,
ao contrário de regex, divisão/`COUNT(DISTINCT)` é portável sem sintaxe
específica de engine. Ambos mutuamente exclusivos com o teste hard
correspondente por construção (faixas `(0, 10]`/`[95, 100)` vs. hard em
exatamente `0.0`/`100.0` ou fato estrutural do schema), e suprimidos quando
a coluna é `chave_primaria` ou já tem o fato estrutural equivalente
(`nao_nulavel`/`unica`).

**Limitação conhecida — `relationships` em FK composta (issue #56):** o
teste é gerado por coluna, uma `relationships` independente por coluna
local → coluna referenciada — testa que cada valor individual existe na
coluna referenciada, não que a combinação das colunas juntas forma uma
linha válida na tabela referenciada (a integridade referencial real de uma
FK composta). Modelar isso de verdade exigiria agrupar colunas de uma
mesma constraint composta no Extraction Context (`ColunaAnalisada.
referencias` é por coluna hoje, sem esse agrupamento) — mudança de escopo
maior que as demais sugestões da auditoria, tocando 3 Bounded Contexts.
Decisão registrada: documentar a limitação, não modelar FK composta nesta
issue.

**Cast SQL:** usa `TipoDeDado.categoria` + atributos de precisão para gerar
`CAST(col AS NUMERIC(10,2))`, `CAST(col AS VARCHAR(255))`,
`CAST(col AS TIMESTAMP WITH TIME ZONE)` etc. `ENUM`/`SET` (MariaDB, issue
#35) não têm equivalente ANSI portável e caem para `VARCHAR`. `UNKNOWN` não
recebe `CAST` — a coluna é projetada raw, sem tipo mapeado não há cast
seguro a fazer.

---

### `GeradorContextoDeIA`

```python
class GeradorContextoDeIA:
    requer: list[type] = [MetricasBaseColuna]

    def __call__(self, entrada: BancoAnalisado, destino: Path) -> Resultado[None]: ...
```

Reabertura de escopo da issue original: em vez de um único `ai_context.json`
com o `BancoAnalisado` inteiro serializado — redundante com Markdown/dbt,
mesma informação, outro parser, e o antipadrão documentado na prática atual
de contexto-pra-agente (schema linking, M-Schema, chunking > dump
monolítico) — o artefato é dividido em três peças, todas deriváveis 100% do
que já está em `BancoAnalisado`, sem Analisador novo e sem dependência nova:

**Saída:** `<destino>/index.json` + `<destino>/tabelas/<escopo>/<tabela>.json`
(um arquivo por tabela, agrupado em subpasta por escopo — issue #77; a
subpasta já desambigua tabela homônima entre escopos, sem precisar do
prefixo `<escopo>__` usado pelo `_nome_model` do `GeradorDbt`, que resolve
um problema diferente — namespace global de model no grafo dbt).

**`index.json`:**
```json
{
  "tabelas": [{"nome_escopo": "...", "nome_tabela": "...", "arquivo": "tabelas/..."}],
  "grafo_de_relacionamentos": {
    "nota_de_escopo": "referenciado_por reflete apenas as tabelas presentes neste lote de análise; se o lote for um subconjunto da fonte, tabelas fora dele que também referenciam a mesma tabela não aparecem aqui.",
    "tabelas": {
      "vendas.pedidos": {
        "referencia": [{"coluna": "cliente_id", "tabela_destino": "vendas.clientes", "coluna_destino": "id"}],
        "referenciado_por": [{"tabela_origem": "vendas.itens_pedido", "coluna_origem": "pedido_id", "coluna": "id"}]
      }
    }
  }
}
```
Grafo bidirecional de relacionamentos via FK real (`chave_estrangeira`/
`referencia`), chave `f"{nome_escopo}.{nome_tabela}"`. `referencia` (saída)
é sempre exaustiva — vem do FK da própria tabela, que está sendo iterada
porque está no lote, então não depende do que mais foi analisado.
`referenciado_por` (entrada) é fundamentalmente diferente: só existe porque
outras tabelas do lote foram inspecionadas e apontavam pra essa. Se o lote
for um subconjunto do banco, uma tabela fora dele que também referencia a
mesma tabela fica invisível — a lista pode aparecer **não-vazia mas
incompleta**, o que é pior que vazia (convida conclusão errada de
exaustividade). Como é limitação estrutural de toda execução (não um caso
pontual), não vira `Aviso` por ocorrência — vira uma nota fixa
(`nota_de_escopo`) sempre presente no artefato, no mesmo espírito da nota
de rodapé de `MetadadosDeAmostra` no `GeradorMarkdown`.

**`tabelas/<escopo>/<tabela>.json`:** dados estruturais + métricas da
tabela (chunk endereçável independentemente, para um agente carregar só o
subconjunto do schema relevante à tarefa) e, quando aplicável, uma seção
`esquema_de_consulta.colunas_filtraveis` (tool/function-calling schema):
sugestão de filtro `enum` quando a coluna não é PK **e**
`_elegivel_para_enumeracao` aprova a coluna (ver os 5 critérios na seção
do `GeradorDbt` acima — issue #95) — reaproveita **exatamente** a mesma
função de `generators/comum/_metricas.py`, já que é a mesma pergunta estatística
que o `GeradorDbt` resolveu para `accepted_values`. A checagem de
`chave_primaria` fica fora da função compartilhada (PK é identificador,
não filtro de enum — regra específica deste Gerador, não de elegibilidade
estatística). `esquema_de_consulta` fica em chave própria, nunca misturada
nos campos descritivos da coluna — separa "dado passivo" de "contrato de
execução".

**`restricoes_fk_compostas` (issue #95):** chave na raiz do chunk,
omitida quando a tabela não tem nenhuma FK composta — mesma convenção de
omissão de `restricoes_unicas`/`metricas_tabela`/`esquema_de_consulta`.
Diferente de `restricoes_unicas` (lista de listas de nomes de coluna),
é lista de **dicts** com `colunas_locais`, `escopo_referenciado`,
`tabela_referenciada`, `colunas_referenciadas` — `RestricaoDeFkComposta`
carrega 4 campos, sem estrutura simples o bastante pra virar lista de
listas sem perder informação (ao contrário de `RestricaoUnica`, que só
carrega `colunas`). Grupos ordenados por `colunas_locais`, mesmo motivo
de determinismo entre reextrações já aplicado a `restricoes_unicas`.

**`referencias` por coluna (issue #105):** cada coluna no chunk carrega
`"referencias": [...]`, lista de `ReferenciaDeColuna` serializadas
(`nome_escopo`, `nome_tabela`, `nome_coluna`), sempre presente — mesmo
vazia — por consistência com os demais campos de **coluna**
(`chave_primaria`, `chave_estrangeira`, etc., que nunca são omitidos),
diferente da convenção de omissão usada pelos campos de **tabela**
(`restricoes_unicas`/`restricoes_fk_compostas` acima). Coluna com 2+
entradas é FK polimórfica sem discriminator — só documentacional aqui,
sem risco de falso positivo (diferente do `GeradorDbt`, que não gera
teste `relationships` pra esse caso, ver seção acima).

Fora de escopo (decisão registrada, não implícita): inferência de
`papel_de_negocio`/`regras_de_negocio` a partir de estatísticas exigiria
exceção formal à Restrição 5 do PRD e fica para issue separada.

---

## CLI (`src/ddf/infrastructure/adapters/cli/`)

### Organização do diretório

```
cli/
├── wizard.py          # @click.command executar() — só orquestra as 14 etapas
├── prompts.py          # único módulo que importa questionary
├── avisos.py           # ou_sair, exibir_avisos — cross-cutting, sem estado
├── validacao.py        # validar_dependencias (produz/requer)
├── etapas/              # uma fase do pipeline por módulo
│   ├── extracao.py      # etapas 1-5: conexão, escopos, amostragem, extração
│   ├── curadoria.py     # etapas 6-8: skeletons, pausa, aplicar sobrescritas
│   ├── analise.py       # etapas 9-11: escolher Geradores, validar, analisar
│   └── geracao.py       # etapas 12-14: destino, confirmar, executar
└── registro/            # pontos de extensão
    ├── comum.py          # registrar_ou_falhar — compartilhado pelos 4 abaixo
    ├── extratores.py      # EXTRATORES_REGISTRADOS (registro só via entry point, issue #67)
    ├── estrategias.py      # ESTRATEGIAS_REGISTRADAS
    ├── analisadores.py      # ANALISADORES_REGISTRADOS (não exposto no wizard, fora de #67)
    ├── geradores.py          # GERADORES_REGISTRADOS (registro só via entry point, issue #67)
    └── descoberta.py          # descobrir_extratores/descobrir_geradores (issue #67)
```

Direção de dependência: `wizard.py` importa `prompts`, `etapas.*`, o
orquestrador e `registro.descoberta` (só para disparar a descoberta de
plugins no início de `executar()`, ver abaixo) — não importa os demais
módulos de `registro.*` diretamente. Cada módulo de `etapas/` depende de
`avisos`/`prompts`/`registro.*`, nunca o contrário.

### Descoberta de plugins (`cli/registro/descoberta.py`, issue #67)

`Extrator` e `Gerador` são reexportados em `domain/ports/__init__.py` como
caminho de import público; plugins de terceiro (`pip install ddf` +
`entry_points(group="ddf.extratores"/"ddf.geradores")`) e os próprios
adapters nativos (declarados em `pyproject.toml`, sem distinção) são
descobertos por `descobrir_extratores`/`descobrir_geradores`, chamadas em
`wizard.py` antes de qualquer etapa. Cada uma isola falha por entry point
(import quebrado, classe fora do Protocol, nome duplicado) como `Aviso`,
sem derrubar a descoberta das demais.

- Entry point de `ddf.extratores` aponta para uma instância pronta de
  `ExtratorRegistrado` (classe + função `construir` interativa) — não dá
  pra genericizar o construtor de um Extrator (cada fonte pergunta um
  conjunto de credenciais diferente). Desde a issue #75, Postgres e
  MariaDB perguntam o mesmo formato — host/porta/banco (ou usuário)/senha
  mascarada separados, DSN do Postgres montada internamente com
  `urllib.parse.quote`; antes o Postgres pedia uma connection string
  inteira em texto claro (senha visível), assimétrico ao MariaDB. Postgres
  também pergunta um campo opcional de parâmetros extra (ex.:
  `sslmode=require`), anexado como query string — cobre Postgres gerenciado
  (RDS, Azure Database, PgBouncer) sem voltar à connection string livre.
- Entry point de `ddf.geradores` aponta direto para a classe (construtor
  sem argumentos, mesmo padrão de `Analisador`).
- `Analisador` **não** entra nesse mecanismo — é a ACL entre Curation e
  Analysis, e todo Analisador registrado roda incondicionalmente em toda
  execução, sem seleção do usuário (diferente de Extrator/Gerador,
  escolhidos em menus do wizard). `cli/registro/analisadores.py` continua
  com registro nativo por chamada direta no import. Ver
  `plan/registry-plan/issue-67-*.md` e a seção de versionamento semântico
  em `docs/engineer_guidelines.md`.

### `wizard.py`

```python
@click.command()
def executar() -> None:
    """Executa o wizard interativo do ddf, da conexão aos artefatos gerados."""
```

Modo `--config`/não-interativo ficou fora de escopo da issue #16 — a
assinatura não reserva esse parâmetro.

**Etapas** (ordem revisada na issue #75 — antes a estratégia de amostragem
era a etapa 1, escolhida sem nenhuma informação sobre fonte/escopo; ver
Decisão 13 do `system_design_doc.md`):

1. Escolher fonte (`EXTRATORES_REGISTRADOS`) e construir o `Extrator`
   (`ExtratorRegistrado.construir`, que pergunta credenciais específicas da
   fonte) — `ConfiguracaoDeExtracao` é construída aqui sem estratégia
   (`estrategia=None`).
2. Testar conexão via `listar_escopos()` — retry manual até 3 tentativas,
   nunca automático com a mesma credencial (risco de lockout de conta).
3. Escolher escopo(s) — reaproveita a lista de `listar_escopos()` (etapa 2),
   sem 2ª chamada de rede.
4. Escolher estratégia de amostragem (`ESTRATEGIAS_REGISTRADAS`) — escolha
   explícita mesmo havendo só `PercentualDeLinhas` hoje; atribuída à mesma
   `ConfiguracaoDeExtracao` construída na etapa 1 (`configuracao.estrategia
   = ...`), já em uso pelo `Extrator`.
5. Extrair em paralelo via `OrquestradorParalelo` — spinner de progresso +
   avisos de sucesso parcial. Total exibido na barra de progresso vem de
   `ao_conhecer_total` (issue #75), não de uma listagem prévia por fora.
6. Gerar/atualizar skeletons de sobrescrita em disco — conta criados/
   atualizados vs. preservados sem mudança.
7. **Pausa:** `prompts.pausar(...)` — usuário edita os YAMLs de overrides
   manualmente antes de continuar.
8. Aplicar sobrescritas (2ª passada, já com a curadoria manual) — gera o
   `BancoCurado`.
9. Escolher Geradores entre os registrados.
10. **Validar dependências** de todos os Analisadores registrados (sempre
    rodam todos, sem seleção do usuário) contra só os Geradores escolhidos
    na etapa 9 — `validar_dependencias` devolve os Analisadores já na ordem
    de execução. Não existe etapa de "escolher Analisadores".
11. Analisar via `compor(*analisadores_ordenados)` sobre `ContextoDeAnalise`
    — spinner + avisos.
12. Escolher destino — diretório raiz, sugestão genérica (`artefatos`).
13. Confirmar — resumo do que será gerado.
14. Executar Geradores — cada um protegido por `executar_com_seguranca`,
    escrevendo sempre na sua própria subpasta (`destino/<slug>`, via
    `_slugificar`), mesmo quando só um Gerador foi escolhido — evita
    misturar artefatos de Geradores diferentes no mesmo diretório quando
    mais de um é escolhido na mesma execução (issue #77). Avisos e caminho
    do artefato exibidos por Gerador.

**Exibição de avisos (`cli/avisos.py::exibir_avisos`):** agrupados por
origem e por "tipo" (mesma forma, identificador normalizado) — as 3
primeiras ocorrências de cada tipo aparecem na íntegra, o restante condensa
numa linha com contagem total. Nunca esconde um tipo diferente.

**Boundary de exceção (issue #56, Decisão 12 do `system_design_doc.md`):**
a etapa 14 é obrigada a envolver cada chamada de Gerador com
`executar_com_seguranca` (`pipeline/seguranca.py`) — mesmo padrão já
aplicado em `compor()` (etapa 11) e no worker de `OrquestradorParalelo`
(etapas 5 e 8). Sem isso, uma exceção não prevista dentro de um Gerador
propagaria crua pro usuário final do wizard, violando a NFR4/RF7 do PRD —
exatamente o risco que motivou a issue #56.

**Código de saída:** `0` em sucesso, `1` em qualquer `Falha` (ou nenhuma
tabela extraída/curada com sucesso — `_sair_se_vazio(itens, mensagem)`,
issue #75, único ponto que decide isso; `OrquestradorParalelo.extrair`/
`aplicar_sobrescritas` nunca devolvem `Falha` por conta própria, mesmo com
lote vazio), `0` também se o usuário cancelar um prompt (Ctrl+C/Esc) ou
recusar a confirmação final.

### Validação de dependências (`cli/validacao.py`)

```python
def validar_dependencias(
    analisadores: dict[str, Analisador],
    geradores: dict[str, Gerador],
) -> Resultado[list[Analisador]]:
    """Valida produz/requer e devolve os Analisadores em ordem de execução."""
```

**Recebe dicts (nome de registro → instância), não listas (issue #75):**
antes as mensagens de erro citavam `type(instancia).__name__` (nome da
classe Python, ex.: "GeradorDbt") em vez do rótulo exibido no menu do
wizard (ex.: "Dbt"). `validar_dependencias` monta um mapa `id(instância) ->
nome` a partir dos dois dicts recebidos e usa esse rótulo (com fallback pro
nome da classe se a instância não estiver no mapa) em toda mensagem de erro
— `cli/etapas/analise.py::validar_selecao` passa `ANALISADORES_REGISTRADOS`
direto e monta o dict dos Geradores escolhidos.

**Comportamento:**
1. Ordena os Analisadores recebidos por dependência topológica de
   `produz`/`requer` — a ordem de seleção do usuário na CLI não determina a
   ordem de execução, só o conjunto selecionado.
2. Para cada Analisador: verifica que seus `requer` estão no conjunto `produz`
   dos Analisadores que vêm antes dele na ordem topológica calculada.
3. Para cada Gerador: verifica que seus `requer` estão no conjunto `produz`
   total dos Analisadores.
4. `Falha` com mensagem listando cada dependência não satisfeita, citando o
   rótulo de registro (não a classe Python) de quem requer e qual
   Analisador produziria ela.
5. `Falha` com mensagem clara se houver ciclo entre `produz`/`requer` dos
   Analisadores selecionados (ex.: A requer o que só B produz, e B requer o
   que só A produz).
6. Em sucesso, `Sucesso(valor=<analisadores ordenados>)` — o wizard usa esse
   valor diretamente em `compor(*analisadores_ordenados)`, sem recalcular a
   ordem.

### Registros de extensão (`cli/registro/`)

Quatro registros com o mesmo padrão — um dict `*_REGISTRADOS`, uma função
`registrar_*` que levanta `ValueError` em nome duplicado, e a população das
implementações nativas no fim do próprio módulo. A checagem de duplicidade
e a inserção são idênticas nos 4, então vivem uma vez só em
`registro/comum.py`:

```python
def registrar_ou_falhar(
    nome: str,
    entidade: str,
    valor: T,
    registro: dict[str, T],
    *,
    feminino: bool = False,
) -> None:
    """Registra `valor` sob `nome` em `registro`; levanta ValueError se já existir."""
```

`feminino` só existe para manter a concordância de gênero da mensagem de
erro (`"Estratégia '...' já está registrada"` vs. `"Extrator '...' já está
registrado"`).

**`registro/extratores.py`** — o único registro cujo valor carrega também o
construtor interativo (`ExtratorRegistrado.construir`, definida em
`domain/ports/extrator.py`, ver seção Ports acima), porque construir um
`Extrator` exige perguntar credenciais específicas da fonte:

```python
EXTRATORES_REGISTRADOS: dict[str, ExtratorRegistrado] = {}

def registrar_extrator(
    nome: str,
    classe_extrator: type[Extrator],
    construir: Callable[[ConfiguracaoDeExtracao], Extrator],
    registro: dict[str, ExtratorRegistrado] = EXTRATORES_REGISTRADOS,
) -> None: ...

_REGISTRO_POSTGRES = ExtratorRegistrado(ExtratorPostgres, _construir_extrator_postgres)
_REGISTRO_MARIADB = ExtratorRegistrado(ExtratorMariaDB, _construir_extrator_mariadb)
```

Desde a issue #67, `PostgreSQL`/`MariaDB` não populam
`EXTRATORES_REGISTRADOS` por chamada direta — `_REGISTRO_POSTGRES`/
`_REGISTRO_MARIADB` só existem como alvo dos entry points declarados em
`pyproject.toml`; quem popula o dict é `registro/descoberta.py`, chamado
por `wizard.py` (ver seção "Descoberta de plugins" acima).

**`registro/estrategias.py`** — mesma forma, mas `EstrategiaRegistrada` só
carrega `construir` (sem `classe_estrategia`: nunca foi lido em produção,
removido na issue #76), para `EstrategiaDeAmostragem`. `PercentualDeLinhas`
e `TabelaInteira` estão registradas — a 2ª estratégia antecipada desde a #9/#16
chegou na #76, sem precisar reabrir `wizard.py`: a escolha já era explícita
no wizard (etapa 4, reordenada na issue #75 — era etapa 1) mesmo quando só
havia uma opção.

**`registro/analisadores.py`/`registro/geradores.py`** — mais simples:
guardam a instância direto (`dict[str, Analisador]`/`dict[str, Gerador]`),
sem construtor interativo, porque `Analisador`/`Gerador` não recebem
argumento no construtor. `ANALISADORES_REGISTRADOS` **não é exposto em
nenhum menu do wizard** — todos os Analisadores registrados sempre rodam
(ver etapa 10); é um ponto de extensão manipulado só por quem desenvolve o
ddf, ou por um plugin de terceiro via a descoberta que a issue #67 constrói
em cima dele. `GERADORES_REGISTRADOS` é o único user-facing (etapa 9).

**Comportamento comum:** todos os 4 são pontos de extensão para novas
implementações sem editar o wizard. Cada `registro` aceita um dict isolado
como parâmetro (default é o `*_REGISTRADOS` global) — testes injetam um
registro próprio em vez de mutar o dict global entre execuções.

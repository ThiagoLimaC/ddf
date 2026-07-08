# Engineering Guidelines — ddf (novo)

Este documento define padrões e boas práticas de engenharia para quem contribuir
com código neste projeto.

> **Antes de iniciar qualquer issue:** leia os documentos de referência do
> projeto na ordem abaixo. Cada decisão de implementação já foi tomada e
> documentada — reimplementar sem consultar os docs gera retrabalho.
>
> 1. [`plan/global.md`](../plan/global.md) — ordem das fases e dependências
> 2. [`docs/system_design_doc.md`](system_design_doc.md) — arquitetura, fluxo
>    de dados e decisões de design
> 3. [`docs/low_level_design.md`](low_level_design.md) — assinaturas, tipos e
>    comportamento esperado de cada componente
> 4. [`plan/tasks.md`](../plan/tasks.md) — checklist da issue específica

---

## Registro de execução por issue (`plan/registry-plan/`)

Toda issue em desenvolvimento tem um arquivo próprio em
`plan/registry-plan/issue-<n>-<slug>.md`, com um checklist simples dos passos
planejados para aquela issue.

- Marcar cada item com `[x]` **imediatamente após concluí-lo** — nunca em
  lote no final. O arquivo reflete o progresso real a cada momento, pois é
  revisado pelo usuário a cada PR ou mudança relevante.
- Se um passo envolver uma decisão técnica não óbvia (ex.: escolha de
  ferramenta, workaround, ajuste de escopo), registrar uma sub-linha logo
  abaixo do item correspondente, não em seção separada.
- O arquivo é enxuto: só os passos definidos e, quando houver, a decisão
  técnica associada — sem narrativa adicional.

---

## Explicação por etapa, antes de seguir

Ao concluir uma etapa do plano de execução de uma issue — tipicamente a
entrega de um arquivo, classe ou método dentro do escopo da task — quem está
implementando (humano ou assistente) **para** e apresenta uma explicação
antes de avançar para a próxima etapa. Isso vale mesmo em modos de execução
automática/contínua — a pausa é deliberada, não um efeito colateral de erro.

A regra vale também para arquivos de teste: cada `test_*.py`/`conftest.py`
entregue é sua própria etapa, com a mesma pausa e explicação antes de seguir
para o próximo arquivo — não apenas para código de produção em `src/`.

A explicação cobre, para o elemento entregue:

- **Posição na arquitetura** — a qual Bounded Context/camada pertence, e como
  se relaciona com a estrutura de Ports & Adapters.
- **Implementações futuras** — se for um `Protocol`/Port, quais classes
  concretas vão implementá-lo e em qual issue.
- **Pontos de referência** — quais outros componentes vão chamar ou depender
  dele daqui para frente.

Isso vale independentemente de a informação já estar documentada em
`low_level_design.md` ou `system_design_doc.md` — a explicação é para
entendimento no momento da implementação, não só consulta posterior à
documentação. Só se avança para a próxima etapa mediante confirmação de quem
acompanha a issue.

---

## Arquitetura: DDD com Bounded Contexts + Hexagonal escopado

O `ddf` usa DDD aplicado por **Bounded Contexts** e Hexagonal aplicado
**apenas onde existe variação real de implementação**. Esses dois princípios
moldam todas as decisões de código.

### Os três Bounded Contexts e suas fronteiras

| Context | Módulo | Representação de coluna |
|---|---|---|
| Extraction | `domain/model/extraction.py` | `ColunaExtraida` |
| Curation | `domain/model/curation.py` | `ColunaCurada` |
| Analysis | `domain/model/analysis.py` | `ColunaAnalisada` |

**Regra:** código do Extraction Context nunca importa tipos do Analysis Context,
e vice-versa. As Anti-Corruption Layers (`SobrescritaDeTabela` e os
Analisadores) são os únicos pontos de tradução entre contextos.

### Métricas como Value Objects — a regra mais importante

`MetricaDeColuna` e `MetricaDeTabela` são Value Objects: imutáveis, sem
identidade própria, definidos pelos seus valores.

**Adicionar uma nova métrica = criar um novo tipo que herda de `MetricaDeColuna`
ou `MetricaDeTabela`.** Nenhum modelo existente muda.

```python
# correto — arquivo novo, zero mudanças em código existente
class MetricasDeDistribuicao(MetricaDeColuna):
    origem: str = "AnalisadorDeDistribuicao"
    assimetria: float
    curtose: float
    histograma: list[tuple[float, float]]
```

**Proibido:** adicionar campos de métrica diretamente em `ColunaAnalisada` ou
`TabelaAnalisada`. Isso viola o Open/Closed e força mudanças em todos os
Geradores existentes.

### Override: responsabilidade única, duas fases internas

A `SobrescritaDeTabela` tem **uma responsabilidade**: produzir `TabelaCurada`
a partir de `TabelaExtraida`. Para cumpri-la, usa duas fases com razões de
mudança distintas:

- `_traduzir` — mapeamento estrutural `ColunaExtraida` → `ColunaCurada`; muda
  quando a estrutura da fonte muda.
- `_aplicar_overrides` — aplica curadoria do YAML; muda quando regras de
  curadoria mudam.

**Regra:** manter essas fases como métodos privados separados dentro do mesmo
componente. **Não criar um componente `TradutorExtractionParaCuration` separado**
— o resultado intermediário não tem significado fora desse fluxo e não justifica
um tipo ou componente próprio.

### Extensão via `Protocol`, nunca via classe orquestradora com `if`s

- Toda nova fonte de dados, heurística de análise ou formato de saída entra
  implementando o `Protocol` correspondente em `domain/ports/` e se conectando
  ao pipeline como mais um item na composição.
- **Proibido reintroduzir uma classe `UseCase`** com `if`s decidindo o que
  rodar.
- Um `Estagio` que não implementa o `Protocol` correspondente não compila
  contra `compor()` — verificado por `mypy --strict`.

### Analisadores e Geradores declaram dependências explicitamente

Todo Analisador e Gerador declara `produz` e/ou `requer`:

```python
class MeuAnalisador:
    produz: list[type] = [MinhaMetrica]
    requer: list[type] = [MetricasBaseColuna]  # depende de AnalisadorDeMetricasDeColuna
```

A CLI valida essas dependências antes de qualquer execução. **Nunca descobrir
dependência em runtime** — o usuário recebe um erro claro antes de qualquer
processamento começar.

### Polars como detalhe de implementação

`pl.DataFrame` existe **apenas** dentro dos modelos `TabelaExtraida`,
`TabelaCurada`, `BancoCurado` e `ContextoDeAnalise`. Nunca atravessa a
fronteira do Analysis Context para os Geradores.

**Regra:** nenhum Gerador importa `polars`. Nenhum modelo além dos listados
acima usa `arbitrary_types_allowed=True`.

---

## Tipagem como garantia, não como documentação

- Os quatro tipos de pipeline (`TabelaExtraida`, `TabelaCurada`,
  `BancoCurado`, `BancoAnalisado`) são estruturalmente distintos —
  `mypy --strict` rejeita qualquer composição que tente pular uma etapa.
- `MetricaDeColuna` como base dos Value Objects garante que Geradores que
  filtram com `isinstance` recebem o tipo correto em tempo de verificação.
- Rode `mypy --strict` localmente antes de cada commit.

---

## Nomenclatura: idioma como contrato

- **Convenções de arquitetura** — estrutura de pastas (`domain/model`,
  `domain/shared`, `domain/ports`, `infrastructure/adapters/...`), nomes de
  módulo e os rótulos dos Bounded Contexts (Extraction, Curation, Analysis) —
  **inglês**, porque são vocabulário do padrão arquitetural, não do domínio de
  negócio.
- **Tudo o que é código** — classes (incluindo classes de domínio e as que
  implementam `Protocol`s), variáveis, parâmetros, funções, campos Pydantic e
  tipagem em geral — **português**, dentro e fora dos limites do pacote.
- **Única exceção:** os artefatos escritos em disco pelo `GeradorDbt`
  (`schema.yml`, `sources.yml`, SQL gerado) usam identificadores em inglês,
  porque esse é o contrato real consumido pelo dbt e pelo warehouse — não uma
  escolha de estilo do código Python. Nenhum outro Gerador tem essa exceção.

---

## Docstrings: resumo de uma linha, Google style

Funções e métodos sem parâmetros (além de `self`) usam só o resumo de uma
linha:

```python
def is_failure(self) -> bool:
    """Verifica se a operação falhou."""
```

Funções e métodos com parâmetros documentam cada um em `Args:`. `Returns:`
só aparece quando o retorno não é `None` — retorno `None` é comunicado pela
própria assinatura (`-> None`), repetir na docstring é redundante:

```python
def extrair_tabela(self, schema: str, tabela: str) -> Resultado[TabelaExtraida]:
    """Extrai estrutura, amostra e metadados de uma tabela específica.

    Args:
        schema: Nome do schema onde a tabela está.
        tabela: Nome da tabela a ser extraída.

    Returns:
        Sucesso com a TabelaExtraida, ou Falha com a descrição do erro.
    """
```

Essa regra vale para todos os Adapters concretos (Extratores, Analisadores,
Geradores, Orquestradores) que implementam os `Protocol`s de
`domain/ports/` — os `Protocol`s em si podem manter só o resumo de uma linha
na assinatura abstrata, e a documentação completa de `Args`/`Returns` vai na
implementação concreta.

---

## Guard-rails de lint e CI

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "D"]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

CI roda `ruff` + `mypy --strict` + `pytest` a cada push, desde o primeiro PR
mergeado. Nenhum PR é mergeado com o pipeline vermelho.

---

# Política de testes

## Cobertura mínima obrigatória, por categoria deliberada

Todo `Estagio` (Extrator, Analisador, Sobrescrita, Gerador, OrquestradorParalelo,
`compor()`) e todo Adaptador novo precisa de, no mínimo, estas três categorias:

1. **Caminho feliz** — comportamento esperado com entrada válida e representativa.
2. **Erro esperado** — falha de domínio real retornando `Falha`, nunca exceção solta.
3. **Borda** — caso limite real do domínio (tabela vazia, coluna sem dados na
   amostra, valor com caractere especial, FK fora da extração atual, amostra
   menor que `tamanho_amostra` configurado).

**O que NÃO conta como borda:** caso que `mypy --strict` já rejeita em tempo
de verificação.

## A pergunta que decide se um teste entra na suíte

**"Que bug real ou regra de negócio este teste pegaria, que não seria pego de
outra forma (tipo, lint, teste já existente)?"** Se "nenhum", o teste não entra.

## Testabilidade por isolamento

Como cada `Estagio` recebe um tipo conhecido e devolve `Resultado` de um tipo
conhecido, o teste de um Analisador novo não exige montar o pipeline inteiro —
só chamar o `Estagio` com a entrada que seu tipo declara.

```
tests/
├── unit/
│   ├── pipeline/                        # compor() e semântica de parar no 1º erro
│   ├── domain/
│   │   ├── model/                       # validação dos modelos Pydantic por Context
│   │   └── shared/                      # Resultado[T], Aviso
│   └── infrastructure/adapters/
│       ├── extractors/                  # conftest.py desde o 1º teste
│       ├── analyzers/                   # conftest.py desde o 1º teste
│       ├── generators/                  # conftest.py desde o 1º teste
│       ├── overrides/
│       └── orchestrator/
└── integration/
    ├── extractors/                      # Postgres real ou containerizado
    └── cli/                             # wizard end-to-end com Extrator fake
```

## `conftest.py` desde o primeiro teste de cada camada

Ao escrever o primeiro teste de uma camada, já criar o `conftest.py`
correspondente com os builders óbvios (ex.: `TabelaExtraida` de fixture,
`ContextoDeAnalise` vazio, `BancoCurado` de fixture).

## Testes de CLI mockam o `Protocol`, nunca o driver de baixo nível

Testes de CLI injetam `Extrator` fake via `FONTES_REGISTRADAS` — nunca mockam
`psycopg2.connect` diretamente.

## Validação de Open/Closed como teste, não só como princípio citado

Sempre que uma `Porta` ganha uma nova implementação real, existe pelo menos um
teste que prova que adicioná-la não exigiu editar nenhuma implementação já
existente. Isso inclui Analisadores: um teste que instancia um Analisador
novo, adiciona ao `compor()`, e verifica que os Analisadores já existentes
produzem exatamente o mesmo resultado que produziam antes.

## Teste de validação de dependências

A função `validar_dependencias(analisadores, geradores)` tem testes para:

- Combinação válida: `AnalisadorDeMetricasDeColuna` + `GeradorDbt` — passa.
- Dependência ausente: `AnalisadorDeMetricasDeTabela` sem
  `AnalisadorDeMetricasDeColuna` — `Falha` com mensagem mencionando
  `MetricasBaseColuna`.
- Gerador sem Analisador correspondente: `GeradorMarkdown` sem
  `AnalisadorDeMetricasDeTabela` — `Falha` mencionando `MetricasBaseTabela`.

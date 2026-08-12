# Issue #8 — feat: Ports e contrato da CLI

- [x] `domain/model/analysis.py` — acrescenta `TipoDeMetrica = type[MetricaDeColuna | MetricaDeTabela]`
  (alias reaproveitado por `Analisador`/`Gerador`, evita repetir a união em dois Ports)

- [x] `domain/ports/extrator.py`
  - `Extrator` (`@runtime_checkable` Protocol) — `listar_tabelas(schema) -> Resultado[list[tuple[str, str]]]`,
    `extrair_tabela(schema, tabela) -> Resultado[TabelaExtraida]`

- [x] `domain/ports/analisador.py`
  - `Analisador` (`@runtime_checkable` Protocol) — `produz: list[TipoDeMetrica]`,
    `requer: list[TipoDeMetrica]`, `__call__(ContextoDeAnalise) -> Resultado[ContextoDeAnalise]`

- [x] `domain/ports/gerador.py`
  - `Gerador` (`@runtime_checkable` Protocol) — `requer: list[TipoDeMetrica]`,
    `__call__(BancoAnalisado, destino: Path) -> Resultado[None]`

- [x] `domain/ports/orquestrador_de_tabelas.py`
  - `OrquestradorDeTabelas` (`@runtime_checkable` Protocol) —
    `extrair(schemas, extrator) -> Resultado[list[TabelaExtraida]]`,
    `aplicar_sobrescritas(tabelas, sobrescrita: Estagio[TabelaExtraida, TabelaCurada]) -> Resultado[BancoCurado]`

- [x] `infrastructure/adapters/cli/fontes.py`
  - `FONTES_REGISTRADAS: dict[str, type[Extrator]]` — inicia vazio (`ExtratorPostgres`
    ainda não existe, é Issue #9; população real fica para lá)
  - `registrar_fonte(nome, classe_extrator, registro=FONTES_REGISTRADAS) -> None`
    — `ValueError` em nome duplicado

- [x] `infrastructure/adapters/cli/validacao.py`
  - `validar_dependencias(analisadores, geradores) -> Resultado[list[Analisador]]`
    — valida `produz`/`requer` (checa ausência primeiro, sem tentar ordenar
    conjunto incompleto), depois ordena topologicamente (Kahn) usando `id()`
    como chave de identidade; ciclo vira `Falha` distinta de dependência ausente

- [x] ~~`infrastructure/adapters/cli/wizard.py`~~ — **removido do escopo desta issue.**
  Chegou a ser implementado como esqueleto (`@click.command()` + 6 funções
  privadas assinadas contra os Ports reais, `# TODO: implementar na Issue 16`),
  passou em `mypy --strict`/`ruff`, mas foi descartado após revisão: como
  nenhuma função chamava a próxima (cada uma só levantava `NotImplementedError`
  isoladamente), o esqueleto não validava composição real do fluxo — só que
  os tipos existiam e importavam, o que os próprios arquivos de Port já
  garantem sozinhos. Sem teste, sem execução possível, sem valor de integração
  real: custo de manutenção sem benefício correspondente. Decisão: `wizard.py`
  nasce do zero na Issue 16, quando houver lógica de verdade para preencher
  cada etapa, em vez de carregar um esqueleto morto até lá. `docs/low_level_design.md`
  mantém a descrição do fluxo completo (seção CLI) como referência para essa
  issue futura — só o arquivo de código foi removido.

## Decisões tomadas na discussão prévia (antes de implementar)

> **Import cruzado de Bounded Contexts nos Ports:** `domain/ports/` importa de
> Extraction, Curation e Analysis ao mesmo tempo (`Extrator` usa `TabelaExtraida`,
> `Analisador` usa `ContextoDeAnalise`, `OrquestradorDeTabelas` usa `TabelaExtraida`/
> `TabelaCurada`/`BancoCurado`). Confirmado que isso **não viola** a regra de
> Bounded Contexts do `CLAUDE.md` — `ports/` é a fronteira hexagonal, não um
> Bounded Context, e é o único lugar com licença para enxergar os três.

> **`@runtime_checkable` em todos os 5 Ports** (não só `EstrategiaDeAmostragem`
> como estava implícito no `low_level_design.md`) — permite `isinstance(fake, Port)`
> nos testes, consistência entre os Ports. Doc atualizado.

> **`validar_dependencias` muda de `Resultado[None]` para `Resultado[list[Analisador]]`**
> (diverge do snippet original do `low_level_design.md`, já corrigido lá). Razão:
> a validação já precisa calcular a ordem topológica de execução para checar
> `requer` corretamente (um Analisador só pode depender do que roda *antes* dele);
> descartar essa ordem obrigaria a Issue 16 (wizard) a recalculá-la, duplicando a
> lógica. `Sucesso` carrega a lista já ordenada, pronta para `compor(*ordenados)`.
> Ciclo entre `produz`/`requer` (ex.: A requer o que só B produz e vice-versa) é
> `Falha` explícita com mensagem de ciclo detectado — não é `Falha` genérica de
> dependência ausente.

> **`registrar_fonte` recebe `registro` injetável** com `FONTES_REGISTRADAS` como
> default — testes passam um dict isolado em vez de mutar o registro global entre
> execuções, sem exigir fixture de save/restore.

> **`wizard.py` sem teste próprio nesta issue** — é esqueleto (`# TODO`), só
> precisa tipar/importar corretamente e passar `mypy --strict` + `ruff`. Os 3
> testes obrigatórios da issue (feliz/erro/borda) valem para `validar_dependencias`.

## Testes (`tests/unit/infrastructure/adapters/cli/`)

> **Testes de conformidade dos Ports (`isinstance(fake, Port)`) foram descartados.**
> Cheguei a escrever `tests/unit/domain/ports/` com Fakes completos + `isinstance`
> para os 4 Ports, todos passando — mas, na revisão, não sobreviveram: eles só
> provam que `@runtime_checkable`/`isinstance()` do Python funcionam contra um
> Fake escrito para bater com o próprio Protocol na mesma sessão, sem nenhum
> caminho de execução real no projeto que faça essa checagem em runtime hoje
> (a conformidade que importa é estática, via mypy, no ponto de uso). Não
> testam nosso código, testam a stdlib. **Decisão:** esse padrão
> (`assert isinstance(<adapter_real>, <Port>)`) deve nascer junto de cada
> implementação concreta futura — `ExtratorPostgres` (#9), `OrquestradorParalelo`
> (#10), `AnalisadorDeMetricasDeColuna`/`DeTabela` (#11/#12), `GeradorMarkdown`/
> `Dbt`/`ContextoDeIA` (#13-#15) — como 1 linha de smoke-test na suíte de cada
> um, onde de fato protege contra um adapter real desviando do contrato.

### `validar_dependencias`

- [x] Caminho feliz: Analisadores com `requer=[]` bem formados + Gerador cujo
      `requer` é satisfeito → `Sucesso` com a lista de Analisadores ordenada
- [x] Caminho feliz: Analisadores passados **fora de ordem** de dependência
      (ex.: `[AnalisadorDeTabela, AnalisadorDeColuna]`) → `Sucesso` com a lista
      **reordenada** corretamente (Coluna antes de Tabela)
- [x] Erro esperado: Gerador exige métrica que nenhum Analisador selecionado produz
      → `Falha` citando a classe do Gerador e a métrica faltante
- [x] Erro esperado: Analisador exige métrica que nenhum Analisador selecionado
      produz → `Falha` citando a classe do Analisador e a métrica faltante
- [x] Borda: ciclo entre `produz`/`requer` de dois Analisadores selecionados →
      `Falha` específica de ciclo (mensagem distinta de dependência ausente)
- [x] Borda: listas vazias de Analisadores e Geradores → `Sucesso` com lista vazia
- [x] Caminho feliz: cadeia transitiva de 3 Analisadores (C depende de B, B
      depende de A), passados em ordem embaralhada → `Sucesso` com ordem A, B, C
      — garante que a topológica não para na primeira camada, resolve em cascata
- [x] Borda: Analisador que `requer` uma métrica do próprio tipo que ele mesmo
      `produz` (auto-dependência, ciclo de 1 nó) → `Falha` de ciclo
- [x] Borda: dois Analisadores selecionados produzem a **mesma** métrica —
      documenta o comportamento atual ("último da lista processado vence" em
      `_mapear_produtores`, sem erro) como intencional, não como bug silencioso

> **Revisão crítica pós-escrita:** ao reaplicar o mesmo critério usado para
> descartar os testes de conformidade dos Ports ("isso testa nosso código ou
> só documenta um acidente de implementação?"), sinalizei que a cadeia
> transitiva de 3 (mecanicamente igual ao teste de reordenação de 2 — mesmo
> branch de código, sem cobrir rodadas com múltiplos nós liberados ao mesmo
> tempo) e a dupla produção da mesma métrica (documenta comportamento não
> especificado por nenhuma regra, não uma garantia pedida) eram candidatos a
> remoção/substituição por um cenário de diamante. Decisão final: **mantidos
> como estão** — não são inúteis a ponto de justificar a troca.

> **Bug encontrado e corrigido durante a escrita dos testes:**
> `_ordenar_topologicamente` misturava dois critérios de igualdade —
> `dependencias`/`resolvidos` indexados por `id()` (identidade), mas
> `restantes.remove(analisador)` usa `==` (`list.remove` busca por igualdade).
> Com Analisadores reais (classes distintas, sem `__eq__` customizado) nunca
> se manifestaria, mas os Fakes de teste (`@dataclass`, que gera `__eq__` por
> valor de campo) expuseram a inconsistência. Corrigido para filtrar
> `restantes` por `id()` também (`[a for a in restantes if id(a) not in
> resolvidos]`), eliminando a mistura de critérios — 100% baseado em
> identidade agora.

### `registrar_fonte` / `FONTES_REGISTRADAS`

- [x] Caminho feliz: `registrar_fonte` com `registro` isolado — nova fonte aparece
      só nesse dict, `FONTES_REGISTRADAS` global permanece intocado
- [x] Erro esperado: registrar nome já existente em `registro` levanta erro
      (`ValueError`) em vez de sobrescrever silenciosamente

## Pendências para próximas issues (não resolvidas aqui)

- Algoritmo exato de ordenação topológica (Kahn vs. DFS) fica a critério da
  implementação de `validar_dependencias` — sem Port ou contrato externo depende disso.
- `wizard.py` real (fluxo completo, retries, streaming de avisos) é Issue 16.

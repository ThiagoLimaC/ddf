# Issue #154 — CLI adapter fino, orquestração em pipeline/

Arquivo de acompanhamento local da issue, commitado nesta branch a pedido
do usuário (histórico do levantamento e do checklist de execução).

## Contexto técnico

Levantamento feito lendo o código real (`wizard.py`, os quatro módulos de
`cli/etapas/`, `cli/validacao.py`) — não é plano especulativo, cada
assinatura abaixo já existe hoje. Toda função de `cli/etapas/*.py` mistura
UI (`prompts.*`, `print`, `sys.exit`) e chamada de Port na mesma função.
Exemplo real (`extracao.py:153-173`):

```python
def extrair(orquestrador, extrator, pares) -> list[TabelaExtraida]:
    inicio = time.monotonic()
    with prompts.progresso_paralelo("Tabelas extraídas", total=len(pares)) as progresso:
        resultado = orquestrador.extrair(pares, extrator, progresso=progresso)  # <- núcleo
    print(); print()
    tabelas = ou_sair(resultado)
    prompts.imprimir_destacado(f"✓ {len(tabelas)} tabela(s) extraída(s).", ...)
    print(f"duração: {time.monotonic() - inicio:.0f}s")
    return tabelas
```

Decisão já fechada com o usuário (ver histórico de conversa, não
reproduzido aqui): **simetria total** — toda função com chamada de Port
move seu núcleo para `pipeline/`, mesmo quando esse núcleo é passthrough de
uma linha (`orquestrador.extrair(pares, extrator, progresso=progresso)`
sozinho), contra a recomendação padrão do arquiteto (que aplicaria a
checklist de indireção decorativa função a função e só moveria as 4 com
lógica de composição real). Decisão consciente, não a reabrir durante a
implementação.

## Inventário função a função

| Arquivo atual | Função | Chama Port? | Núcleo (o que move) | Fica em `cli/etapas/` |
|---|---|---|---|---|
| `extracao.py` | `conectar` | Não direto (delega a `_testar_conexao`) | — | Delegação + escolha de fonte (`prompts.selecionar`) |
| `extracao.py` | `_testar_conexao` | Sim — `extrator.listar_escopos()` | 1 chamada | Loop de retry (`while`, `prompts.confirmar("Tentar novamente?")`, `sys.exit`) |
| `extracao.py` | `configurar_amostragem` | Não (`registro.construir()`, não é Port) | — | Fica inteira em `cli/etapas/` |
| `extracao.py` | `listar_pares` | Sim — `extrator.listar_tabelas(escopo)` em loop | Agregação com sucesso parcial (regra real: falha de 1 escopo não aborta os demais) | Só `exibir_avisos` |
| `extracao.py` | `escolher_tabelas` | Não | — | Fica inteira |
| `extracao.py` | `extrair` | Sim — `orquestrador.extrair(...)` | 1 chamada | Barra de progresso, `ou_sair`, print duração |
| `curadoria.py` | `curar` | Não direto (delega) | — | `prompts.pausar(...)` |
| `curadoria.py` | `_gerar_skeletons` | Sim — `orquestrador.aplicar_sobrescritas(...)` (resultado descartado) | 1 chamada, mesma da linha abaixo | Barra de progresso, mensagem de contagem criados/preservados |
| `curadoria.py` | `aplicar_sobrescritas` | Sim — `orquestrador.aplicar_sobrescritas(...)` (resultado usado) | 1 chamada, mesma acima | Barra de progresso, `ou_sair`, print duração |
| `analise.py` | `escolher_geradores` | Não | — | Fica inteira |
| `analise.py` | `validar_selecao` | Sim — `validar_dependencias(...)` | Já puro (só realoca) | `ou_sair` |
| `analise.py` | `analisar` | Sim — `compor(*analisadores)(...)` | `iniciar_contexto` + `compor()` + extrai `.analisado` | Spinner, prints de aviso/erro, print duração |
| `geracao.py` | `confirmar_execucao` | Não | — | Fica inteira |
| `geracao.py` | `executar_geradores` | Sim — `gerador(banco_analisado, destino_gerador)` em loop | Loop + `_slugificar` + `executar_com_seguranca` | Prints de aviso/sucesso/falha por Gerador |

`_gerar_skeletons`/`aplicar_sobrescritas` chamam literalmente a mesma Port
com os mesmos argumentos — vira **uma função só** em `pipeline/curadoria.py`,
reusada pelos dois call sites (1º call site descarta o `BancoCurado`
retornado, 2º usa). Esse é o único caso de reuso real de 2+ call sites
entre os candidatos "passthrough".

## Novos módulos em `pipeline/`

### `pipeline/validar_dependencias.py`
Movido de `cli/validacao.py` sem alteração de conteúdo (já era puro — zero
import de `questionary`/`prompts`). Só o import em `analise.py` muda.

### `pipeline/extracao.py`
```python
def testar_conexao(extrator: Extrator) -> Resultado[list[str]]:
    """Único ponto que chama Extrator.listar_escopos()."""
    return extrator.listar_escopos()

def listar_pares(extrator: Extrator, escopos: list[str]) -> tuple[list[tuple[str, str]], list[Aviso]]:
    """Agrega Extrator.listar_tabelas() por escopo, sucesso parcial.

    Devolve os avisos em vez de exibi-los — quem exibe é o wrapper de UI
    (diferente do `listar_pares` atual, que já chama `exibir_avisos`
    internamente; aqui a exibição sai do núcleo).
    """
    ...

def extrair_tabelas(
    orquestrador: OrquestradorDeTabelas,
    extrator: Extrator,
    pares: list[tuple[str, str]],
    progresso: Callable[[str], None] | None = None,
) -> Resultado[list[TabelaExtraida]]:
    return orquestrador.extrair(pares, extrator, progresso=progresso)
```

`_testar_conexao` (CLI) mantém o loop de retry (`while`/`prompts.confirmar`),
chamando `pipeline.extracao.testar_conexao(extrator)` a cada iteração.

### `pipeline/curadoria.py`
```python
def aplicar_sobrescritas_em_lote(
    orquestrador: OrquestradorDeTabelas,
    sobrescrita: SobrescritaDeTabela,
    tabelas: list[TabelaExtraida],
    progresso: Callable[[str], None] | None = None,
) -> Resultado[BancoCurado]:
    return orquestrador.aplicar_sobrescritas(tabelas, sobrescrita, progresso=progresso)
```
`_gerar_skeletons` (CLI) chama isso e descarta `.valor`; `aplicar_sobrescritas`
(CLI) chama isso e usa `.valor`. Mesma função, dois wrappers de UI distintos.

### `pipeline/analise.py`
```python
def analisar(
    analisadores_ordenados: list[Analisador], banco_curado: BancoCurado
) -> Resultado[BancoAnalisado]:
    """Move o corpo de etapas/analise.py::analisar, exceto spinner/prints.

    Hoje a função atual faz sys.exit(1) direto em Falha (linha 61) — aqui
    devolve Resultado, o sys.exit fica só no wrapper de UI.
    """
    contexto = iniciar_contexto(banco_curado)
    resultado = compor(*analisadores_ordenados)(contexto)
    if isinstance(resultado, Falha):
        return resultado
    return Sucesso(valor=resultado.valor.analisado, avisos=resultado.avisos)
```

### `pipeline/geracao.py`
```python
class ResultadoDeGerador(NamedTuple):
    """Resultado da execução de um Gerador — nome, destino e Resultado."""

    nome: str
    destino: Path
    resultado: Resultado[None]


def executar_geradores(
    nomes_geradores: list[str],
    geradores_registrados: dict[str, Gerador],
    banco_analisado: BancoAnalisado,
    destino: Path,
    progresso: Callable[[ResultadoDeGerador], None] | None = None,
) -> list[ResultadoDeGerador]:
    """Move o loop de etapas/geracao.py::executar_geradores.

    Devolve a lista de `ResultadoDeGerador` (nome, destino do artefato,
    Resultado) em vez de imprimir — o wrapper de UI decide o que exibir e
    quando sair com código 1. `_slugificar` migra junto (só usada aqui).

    `progresso`, se informado, é chamado uma vez por Gerador, logo após
    ele terminar — preserva a exibição incremental (aviso/sucesso/falha
    por Gerador, à medida que cada um roda) que a versão atual já tem,
    em vez de a UI só saber de tudo depois que o loop inteiro terminou.
    """
    ...
```

`NamedTuple` em vez de `tuple[str, Path, Resultado[None]]` cru — decisão da
banca de revisão (arquiteto-de-software): 3 campos heterogêneos, cada um
lido mais de uma vez no wrapper de UI (`resultado` tanto para avisos quanto
para `isinstance(..., Falha)`, `nome` em duas mensagens diferentes) — acesso
por nome (`item.resultado`) é mais legível que por índice (`item[2]`) sem
custar função nova. `mypy --strict` já pega troca de posição porque os três
tipos são distintos entre si — o ganho aqui é só legibilidade, não segurança
de tipo adicional.

## Ordem de implementação (uma etapa por vez, pausa+explicação a cada arquivo)

1. `pipeline/validar_dependencias.py` (mover) + teste movido
2. `pipeline/extracao.py` (novo) + `tests/unit/pipeline/test_extracao.py`
3. `pipeline/curadoria.py` (novo) + `tests/unit/pipeline/test_curadoria.py`
4. `pipeline/analise.py` (novo) + `tests/unit/pipeline/test_analise.py`
5. `pipeline/geracao.py` (novo) + `tests/unit/pipeline/test_geracao.py`
6. `cli/etapas/extracao.py` — reescrever as 3 funções que chamam pipeline
7. `cli/etapas/curadoria.py` — reescrever `_gerar_skeletons`/`aplicar_sobrescritas`
8. `cli/etapas/analise.py` — reescrever `validar_selecao`/`analisar`
9. `cli/etapas/geracao.py` — reescrever `executar_geradores`
10. `cli/validacao.py` — remover arquivo
11. `wizard.py` — atualizar imports (nenhuma lógica muda)
12. Reduzir/ajustar `tests/unit/infrastructure/adapters/cli/etapas/test_*.py`
    para cobrir só comportamento de UI (fake de `pipeline.*` no lugar de
    fake de Port direto)
13. `docs/engineer_guidelines.md` — nova seção com a regra de simetria total
14. Gates finais: `mypy --strict src`, `ruff check .`, `pytest` completo
    (unit + `tests/integration/cli/test_wizard_end_to_end.py`)

## Testes — o que cada camada passa a verificar

- `tests/unit/pipeline/*` — categorias feliz/erro/borda contra fake de
  Port (`Extrator`/`OrquestradorDeTabelas`/`Analisador`/`Gerador` fake),
  **sem** importar `questionary`/`prompts` em nenhum desses arquivos —
  critério de aceite direto: `grep -L questionary tests/unit/pipeline/*.py`
  deve listar todos.
- `tests/unit/infrastructure/adapters/cli/etapas/*` — passam a fakear
  `pipeline.*` (não mais o Port/Orquestrador direto) e verificam só: retry
  de conexão até 3x, formatação de mensagem, código de saída, ordem de
  prints. Teste que hoje verifica o resultado de `orquestrador.extrair(...)`
  (ex.: conteúdo de `TabelaExtraida`) migra para `tests/unit/pipeline/`.

## Critérios de aceite (mesmos da issue, com verificação exata)

1. `grep -rn "\.extrair(\|\.aplicar_sobrescritas(\|\.listar_tabelas(\|\.listar_escopos(\|compor(" src/ddf/infrastructure/adapters/cli/` → vazio.
2. `mypy --strict src` + `ruff check .` + `pytest` limpos.
3. `tests/integration/cli/test_wizard_end_to_end.py` verde sem alteração.
4. Regra de simetria total documentada em `docs/engineer_guidelines.md`,
   próxima à seção "Extensão via Protocol, nunca via classe orquestradora".

## Escopo adicional — divisão inbounds/outbounds (absorvido da #151)

A issue #151 (`refactor(adapters): divide infrastructure/adapters em
inbounds (CLI) e outbounds`) foi fechada como "completed" sem nenhum
vestígio no repositório (sem commit, branch ou PR) — excluída do GitHub a
pedido do usuário. O conteúdo técnico continua válido; absorvido aqui
porque esta issue já mexe pesado na mesma árvore (`cli/etapas/`).

**Decisão herdada da #151, reafirmada:** nenhuma Port de interface é
criada por este movimento. `cli/prompts.py` (as ~15 primitivas de
terminal) teria uma única implementação real e zero consumidor fora do
próprio adapter — mesmo critério de indireção decorativa já usado para
não criar Port em cima de `pipeline/`. O Port de interação honesto, se um
dia existir, emerge com a TUI (#79) — precedente interno:
`EstrategiaDeAmostragem` só virou `Protocol` quando `TabelaInteira` criou
a segunda implementação real.

**Contagem de referência (medida nesta sessão, antes dos passos 6-14 —
reconferir no momento de executar, já que os passos acima tocam
`cli/etapas/`):** 27 arquivos com `infrastructure.adapters.cli`/
`infrastructure/adapters/cli` em `src/`+`tests/`; 71 arquivos com
`infrastructure.adapters.{extractors,generators,analyzers,orchestrator,
overrides}`. Volume real, não estimativa.

### Passos

15. `git mv` das 6 subárvores em `src/ddf/infrastructure/adapters/`:
    `cli/` → `inbounds/cli/`; `extractors/`, `generators/`, `analyzers/`,
    `orchestrator/`, `overrides/` → `outbounds/`. Espelhar os mesmos
    `git mv` em `tests/unit/infrastructure/adapters/`. Executar **depois**
    dos passos 6-12 (núcleo já extraído para `pipeline/`) — mover diretório
    antes disso obrigaria reescrever todo import intermediário duas vezes.
16. `__init__.py` novos em `adapters/inbounds/` e `adapters/outbounds/`.
17. Atualizar todos os imports absolutos afetados (recontar em `src/`+
    `tests/` no momento da execução — a contagem acima já está defasada
    pelos passos 6-14). Inclui as strings de monkeypatch de teste
    (`ddf.infrastructure.adapters.inbounds.cli.prompts.*`) usadas por
    `unittest.mock.patch`.
18. `pyproject.toml`: os 5 entry points (2 `ddf.extratores` → 
    `adapters/inbounds/cli/registro/extratores.py`; 3 `ddf.geradores` →
    `adapters/outbounds/generators/*`). Grupos (`ddf.extratores`/
    `ddf.geradores`) não mudam — contrato público da #67.
19. `uv pip install -e .` obrigatório após o movimento — a instalação
    editável cacheia `entry_points.txt` no dist-info (achado original da
    #96); sem reinstalar, testes de integração que resolvem entry points
    nativos quebram com `ModuleNotFoundError` apontando o path antigo.
20. Docs internas: `docs/low_level_design.md` (seções com paths
    `adapters/extractors/`, `adapters/overrides/`, `adapters/orchestrator/`,
    `adapters/analyzers/`, `adapters/generators/`, `adapters/cli/`) +
    `docs/engineer_guidelines.md` (seção Nomenclatura e árvore de testes).
    Docs públicas (README, `site_docs/`) — conferir se citam path de
    adapters antes de assumir que não mudam (a #78 avançou desde a #151
    original).
21. Gates: `mypy --strict src`, `ruff check .`, `pytest` completo.
22. `uv build --wheel` + inspeção em venv limpo: `entry_points.txt` do
    wheel aponta para os paths novos, `import ddf` resolve o `main`.

### Fora de escopo (herdado da #151)

- Achatar `cli/` em `inbounds/` sem subpasta — `etapas/`/`registro/`
  continuam subpacotes de `inbounds/cli/`.
- Renomear o que já existe além do enxerto `inbounds/`/`outbounds/` (ex.:
  `orchestrator/` → `orquestrador/`).
- Tratamento distinto para `overrides/` (ex.: top-level `acls/`) — fica em
  `outbounds/` junto de `analyzers/`, mesma justificativa da #151 (eixo
  direção × port-ness é ortogonal, separar só `overrides/` seria
  inconsistente).
- Acoplamento concreto→concreto pré-existente
  (`OrquestradorParalelo` → `MARCADOR_AVISO_PARALELISMO_SEM_SNAPSHOT` de
  `extrator_mariadb.py`) — só muda de endereço, não vira issue própria
  aqui.

## Follow-up fora desta issue

- Atualizar `site_docs/arquitetura/` (diagrama Domain→Ports→Adapters
  publicado pela #78) para refletir a camada `pipeline/` como o único
  ponto de chamada às Ports a partir de um adapter inbound — anotado no
  registry-plan da #78.

## Revisão da banca (arquiteto-de-software, engenheiro-de-dados, po-revisor)

Aprovado pelos três, sem bloqueador. Achados incorporados ao plano:

- **`listar_pares`** (engenheiro-de-dados): o wrapper em `cli/etapas/extracao.py`
  precisa chamar `exibir_avisos(avisos)` **exatamente uma vez** e devolver só
  `pares` (não a tupla) — `wizard.py:129-132` espera `list[tuple[str, str]]`
  direto (inclusive `_sair_se_vazio` logo depois). Teste unitário dedicado a
  isso no passo 6.
- **`executar_geradores`** (po-revisor): exibição hoje é incremental
  (aviso/sucesso/falha por Gerador, durante o loop) — se `pipeline/geracao.py`
  só devolvesse a lista completa ao final, isso viraria exibição em lote,
  regressão de UX real (RNF-8 do PRD). Resolvido com `progresso: Callable[...]`
  opcional, chamado por item, mesmo padrão já usado em `extrair`/
  `aplicar_sobrescritas`.
- **`ResultadoDeGerador` como `NamedTuple`** (arquiteto-de-software): ver
  seção `pipeline/geracao.py` acima.
- **Escopo da "simetria total"** (arquiteto-de-software): a seção nova em
  `engineer_guidelines.md` (passo 13) deixa explícito que a exceção é restrita
  à fronteira `cli/`→`pipeline/`, não é precedente geral contra a checklist de
  indireção decorativa.
- **Critério de aceite reforçado** (po-revisor + engenheiro-de-dados): teste
  cobrindo texto/ordem exata de avisos em cenário de falha parcial — não só
  "algum aviso apareceu" — para `listar_pares` (1 escopo falhando entre
  vários) e `executar_geradores` (1 Gerador falhando entre vários).

## Checklist de execução

- [x] 1. `pipeline/validar_dependencias.py` (mover de `cli/validacao.py`) +
      teste movido de `tests/unit/infrastructure/adapters/cli/test_validacao.py`
      para `tests/unit/pipeline/test_validar_dependencias.py`
- [x] 2. `pipeline/extracao.py` (novo) + `tests/unit/pipeline/test_extracao.py`
- [x] 3. `pipeline/curadoria.py` (novo) + `tests/unit/pipeline/test_curadoria.py`
- [x] 4. `pipeline/analise.py` (novo) + `tests/unit/pipeline/test_analise.py`
- [x] 5. `pipeline/geracao.py` (novo, com `ResultadoDeGerador` e `progresso`
      opcional) + `tests/unit/pipeline/test_geracao.py`
- [x] 6. `cli/etapas/extracao.py` — reescrever `_testar_conexao`,
      `listar_pares` (reconciliar tupla → `list[pares]` + `exibir_avisos` 1x),
      `extrair`
- [x] 7. `cli/etapas/curadoria.py` — reescrever `_gerar_skeletons`/
      `aplicar_sobrescritas` para consumir `aplicar_sobrescritas_em_lote`
- [x] 8. `cli/etapas/analise.py` — reescrever `validar_selecao`/`analisar`
- [x] 9. `cli/etapas/geracao.py` — reescrever `executar_geradores` com
      callback `progresso` preservando exibição incremental
- [x] 10. Remover `cli/validacao.py` (já concluído no passo 1)
- [x] 11. `wizard.py` — atualizar imports (sem mudar lógica; confirmado que
      nenhuma mudança foi necessária, já importava só `cli.etapas.*`)
- [x] 12. Reduzir/ajustar `tests/unit/infrastructure/adapters/cli/etapas/test_*.py`
      para fakear `pipeline.*`; auditar duplicação com `tests/unit/pipeline/*`;
      adicionar teste de ordem/texto exato de avisos em falha parcial
- [x] 13. `docs/engineer_guidelines.md` — nova seção de simetria total,
      escopo restrito à fronteira `cli/`→`pipeline/`
- [x] 14. Gates finais: `mypy --strict src`, `ruff check .`, `pytest`
      completo (unit + `tests/integration/cli/test_wizard_end_to_end.py`
      sem alteração)

## Adendo: reorganização de `pipeline/` em `comum/` + `etapas/`

Fora do checklist numerado original — decisão tomada em conversa com o
usuário durante a implementação, após o passo 12: `pipeline/` estava
misturando mecanismo genérico de composição (`compor.py`, `estagio.py`,
`seguranca.py` — reusado inclusive fora de `pipeline/`, por
`OrquestradorParalelo`) com núcleo específico de cada etapa do wizard
(`extracao.py`, `curadoria.py`, `analise.py`, `geracao.py`,
`validar_dependencias.py`). Import ≠ injeção de dependência: os três
primeiros não têm variação real de implementação (diferente de
Extrator/Gerador/Analisador, que são Protocol por terem 2+ implementações
concretas), então import direto é o desenho certo, sem precisar de Port.

```
pipeline/
├── comum/
│   ├── compor.py       # composição sequencial genérica de Estagios
│   ├── estagio.py       # Protocol Estagio
│   └── seguranca.py     # executar_com_seguranca
└── etapas/
    ├── validar_dependencias.py
    ├── extracao.py
    ├── curadoria.py
    ├── analise.py
    └── geracao.py
```

`tests/unit/pipeline/` espelha a mesma divisão (`comum/`, `etapas/`), com
`conftest.py` próprio em cada subpasta (fixtures de `Estagio[int,int]` em
`comum/`, fixtures de `TabelaExtraida`/`TabelaCurada` em `etapas/`).
Todos os imports em `src/` e `tests/` foram atualizados via `git mv` +
substituição de path; nenhum conteúdo de módulo mudou.

- [x] 15. `git mv` das 6 subárvores (`cli/`→`inbounds/cli/`;
      `extractors/`/`generators/`/`analyzers/`/`orchestrator/`/
      `overrides/`→`outbounds/`), espelhado em `src/`, `tests/unit/` e
      `tests/integration/` (esse último não estava no plano original,
      também tinha `cli/`/`extractors/`/`generators/` para mover)
- [x] 16. `__init__.py` novos em `inbounds/`/`outbounds/`
- [x] 17. Imports absolutos atualizados + strings de monkeypatch de
      teste (achado extra: `tests.unit.infrastructure.adapters.cli...`
      em `test_descoberta.py`, path de import de teste, não pego pelo
      sed de `ddf.infrastructure...`)
- [x] 18. `pyproject.toml` — 5 entry points apontando pros paths novos
      (já resolvido pelo sed geral do passo 17, mesma varredura)
- [x] 19. `uv pip install -e .` (cache de `entry_points.txt`) — achado
      extra: pacote editável duplicado `ddf-framework` (resíduo de rename
      anterior do projeto, mesmo diretório fonte) poluindo
      `importlib.metadata.entry_points()` com paths antigos; removido via
      `uv pip uninstall ddf-framework`
- [x] 20. Docs internas — `low_level_design.md` tinha path com `/`
      (`infrastructure/adapters/cli/...`), não pego pelo sed de import
      dotted; corrigido. `engineer_guidelines.md` já estava limpo.
      `site_docs/` ainda não existe (issue #78 não implementada) — nada a
      conferir. Histórico em `plan/registry-plan/*` (issues já fechadas)
      mantido como estava — não é doc de estado atual.
- [x] 21. Gates: `mypy --strict` (196 arquivos), `ruff check .`
      (line-length subiu de 88→100 em `pyproject.toml`, decisão do
      usuário — paths mais fundos com `inbounds`/`outbounds` estouravam
      88 em ~80 linhas de import, sem forma sintática de quebrar um path
      pontilhado), `pytest` completo (787 passed, 17 deselected/
      benchmark) — todos verdes.
- [x] 22. `uv build --wheel` em venv limpo + inspeção de `entry_points.txt`
      — wheel buildado, extraído e `entry_points.txt` inspecionado
      diretamente (paths novos confirmados); instalado numa venv Python
      isolada (fora do repo, sem `uv`/editable) e os 5 entry points +
      console script `ddf` resolvem e carregam de ponta a ponta.

## Incidente durante a implementação: `git stash` sem aviso

Entre os passos 21 e 22, um `git stash` externo (do usuário, sem avisar
a sessão) fez o working tree parecer ter perdido toda a reorganização
`inbounds`/`outbounds` (passos 15-21) — `git status` limpo, diretórios
novos ausentes, só resíduo de `__pycache__`. Investigação (reflog,
`git ls-files`, busca por arquivos `.py` reais vs. só bytecode) confirmou
que nada tinha sido commitado destrutivamente; era só a stash. Usuário
confirmou (`git stash pop`) e a suíte completa (787 testes) voltou a
passar sem alteração de conteúdo. Lição: ao encontrar working tree
inconsistente com o histórico recente da própria sessão, investigar
(`git reflog`, `git stash list`, `git ls-files` vs. arquivos reais no
disco) antes de assumir perda de trabalho ou tentar refazer do zero.

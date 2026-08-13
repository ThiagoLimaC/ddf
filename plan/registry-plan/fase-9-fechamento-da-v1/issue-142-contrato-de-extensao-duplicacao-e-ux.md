# Issue #142 — chore: fecha contrato de extensão, duplicação interna e feedback do wizard antes da v1

## Contexto

Mesma auditoria de fechamento de v1 das #140/#141. Achados sem decisão de
produto pendente — nenhum exige escolher entre alternativas de negócio, só
implementação. Agrupados por afinidade em três blocos: contrato de
extensão/plugin, duplicação interna, e feedback visual do wizard.

## Decisões tomadas na discussão prévia (antes de implementar)

> **Sinal de "streaming ativado" (bloco 3): reintroduzir usando o mesmo
> padrão visual já usado na etapa de análise** — decisão do usuário. A etapa
> de análise (`etapas/analise.py::analisar`) envolve a chamada longa em
> `with prompts.barra_indeterminada("Analisando..."):`, um spinner que já
> convive bem com `imprimir_destacado`/avisos, sem o problema de colisão que
> o log `WARNING` cru tinha (motivo da remoção original na #116). **Ponto
> técnico a confirmar durante a implementação:** a extração já está dentro
> do redraw `\r` do `progresso_paralelo` (barra determinada N/total) — não
> dá pra simplesmente aninhar um segundo `barra_indeterminada` por cima sem
> repetir o mesmo tipo de conflito que motivou a #116 a reverter o indicador
> "em andamento" por nome de tabela. Investigar se o sinal deve (a)
> substituir/complementar o texto já exibido pela barra da extração quando
> uma tabela grande ativa streaming (mesma barra, mensagem diferente), em
> vez de uma segunda barra independente, ou (b) só disparar quando a
> extração daquela tabela específica não está correndo em paralelo com
> outras.

> **Seed default de amostragem: fixar valor estável** — decisão do usuário,
> em vez de aceitar o churn de diff entre reextrações sem mudança real na
> fonte.

## Bloco 1 — Contrato de extensão/plugin

### 1.1. `py.typed` ausente do pacote

**Arquivo:** `src/ddf/` (arquivo inexistente) + config de build em
`pyproject.toml`

Não há marcador PEP 561 em lugar nenhum; confirmado que o wheel gerado
(`uv build`) também não o contém. `mypy --strict` contra qualquer código fora
de `src/` que importe `ddf.domain.ports.*` reporta `module is installed, but
missing library stubs or py.typed marker` — isso já acontece com a própria
suíte (`mypy --strict --explicit-package-bases tests` → 352 erros em 78
arquivos, maioria em cascata desse erro). Sem o marcador, a política de
semver de `domain/ports/extrator.py`/`gerador.py` (que a #67 existe para
sustentar) não tem como ser verificada por quem escrever um plugin de
terceiro.

**Correção:** criar `src/ddf/py.typed` (vazio); confirmar que o build
(`uv_build`, `[build-system]` do `pyproject.toml`) inclui arquivos não-`.py`
do pacote — validar reconstruindo o wheel e checando o `.whl` com `zipfile`.

### 1.2. `OrquestradorDeTabelas.aplicar_sobrescritas` sem positional-only

**Arquivo:** `src/ddf/domain/ports/orquestrador_de_tabelas.py:40-46`

Único método de Port do projeto sem `/`. O irmão `extrair` (linha 33) já tem.
Provado com `mypy --strict`: uma chamada por keyword
(`orq.aplicar_sobrescritas(tabelas=..., sobrescrita=...)`) passa limpo contra
o tipo do Port hoje — quebra em `TypeError` de runtime no dia em que um
`OrquestradorDistribuido` (já citado no `system_design_doc.md`, Decisão 8)
nomear os parâmetros de outro jeito. Pela política de semver do projeto,
corrigir isso depois da tag é breaking change (major bump); antes, é grátis.

**Correção:** adicionar `/` depois de `sobrescrita` na assinatura.

### 1.3. `tests/` fora do `mypy --strict`

**Arquivo:** `pyproject.toml:64-65` (`files = ["src"]`)

Os fakes de teste são a prova de que os Ports são implementáveis — hoje não
são verificados. Combinado com 1.1, a garantia "um fake que não implementa o
Protocol não compila contra `compor()`" (`engineer_guidelines.md`) só vale
para `src/`.

**Correção:** incluir `tests` no escopo do `mypy --strict` (checar se, depois
de 1.1 resolvido, ainda sobra erro genuíno a corrigir — o volume de 352 erros
medido nesta auditoria era majoritariamente em cascata do `py.typed` ausente,
não necessariamente 352 problemas reais).

### 1.4. Doc desatualizado: "quatro Ports", existem 5; 2 Ports sem política de extensão

**Arquivo:** `docs/system_design_doc.md:29`

Lista Extrator, Analisador, Gerador, `OrquestradorDeTabelas` como "as quatro
Ports". `domain/ports/` tem um 5º Protocol `@runtime_checkable`
(`EstrategiaDeAmostragem`) com 3 implementações reais e menu próprio no
wizard — satisfaz a própria definição de "Porta" que o doc usa para
justificar as outras quatro.

Estado da política de extensão por Port:

| Port | Reexportado em `ports/__init__` | Entry point | Política escrita |
|---|---|---|---|
| `Extrator` | sim | `ddf.extratores` | semver completo |
| `Gerador` | sim | `ddf.geradores` | semver completo |
| `Analisador` | não | não | exclusão justificada por escrito |
| `EstrategiaDeAmostragem` | não | não | **nenhuma** |
| `OrquestradorDeTabelas` | não | não | **nenhuma** |

Para `Analisador`, a exclusão está correta e documentada — sem drift. Para os
outros dois é lacuna de documentação, não decisão tomada.

**Correção:** corrigir a lista de Ports no `system_design_doc.md`; escrever
política (ainda que seja "sem plugin de terceiro por ora, motivo X") para
`EstrategiaDeAmostragem` e `OrquestradorDeTabelas`.

### 1.5. Calibração de limiares nunca fechada (3ª aparição)

**Arquivos:** `extractors/comum/ler_amostra_em_lotes.py:9-31`
(`_LIMIAR_LINHAS_STREAMING=100_000`/`_LIMIAR_BYTES_STREAMING=100_000_000`),
`extractors/comum/leitura_paralela_intra_tabela.py:16-22` (500k linhas/500MB)

Seguem marcados "candidatos, não calibrados" desde #114/#126. O compromisso
de "calibrar depois" foi registrado 2x no registry-plan e nunca virou issue
rastreável (confirmado: não existe issue de calibração aberta). O `K` do
MariaDB, em contraste, já fechou como regra adaptativa
(`extrator_mariadb.py:66-84`) — não precisa reabrir.

**Ação:** decidir valor definitivo com justificativa escrita, ou abrir issue
formal de calibração antes de fechar esta issue — "ainda pendente" sem
rastro não é mais aceitável nesta rodada.

## Bloco 2 — Duplicação interna

### 2.1. Mesmo algoritmo de particionamento duplicado por motor

`postgres/_construcao.py:104` (`particoes_de_blocos`) e
`mariadb/_construcao.py:276` (`particionar_faixas_exaustivas`) são a mesma
aritmética: `particoes_de_blocos(T, n) ≡ particionar_faixas_exaustivas(0,
T-1, n)`.

**Correção:** extrair para `extractors/comum/particionamento.py`.

### 2.2. `colunas_em_fk_composta` calculado duas vezes

`markdown/_filtros.py:155-159` e `dbt/_yaml.py:127-129` — mesmo cálculo, dois
estilos. `generators/comum/_metricas.py` já existe como casa pra regra
compartilhada entre Geradores.

**Correção:** mover para `generators/comum/`.

### 2.3. Categoria de teste declarada ≠ conteúdo, nos 3 Geradores

`test_gerador_markdown.py:159`, `test_gerador_dbt.py:311`,
`test_gerador_contexto_de_ia.py:126` — teste de erro (`Falha` ao não
conseguir escrever em disco) dentro de `class TestFeliz`. Nenhum dos três
arquivos tem `class TestErro`.

**Correção:** reclassificar nos três arquivos.

## Bloco 3 — Feedback visual do wizard

### 3.1. `_configurar_logging()` nunca chamada — regressão silenciosa da própria #116

`wizard.py:51-63,80-92` — a função existe, é testada isoladamente, mas a
chamada foi removida no commit `eaf0da8` (evitar log colidindo com redraw
`\r` da barra de progresso) sem documentar a decisão. Três fontes (doc,
docstring, código) descrevem comportamentos diferentes; o cenário de origem
da #116 (tabela outlier ativando streaming) hoje não emite nenhum sinal.

**Correção:** ver "Decisões tomadas" acima. Corrigir também
`docs/system_design_doc.md:182-183` e a docstring de `_configurar_logging`
para refletirem o comportamento real depois da correção.

### 3.2. Curadoria paralela usa spinner indeterminado, não barra real

`cli/etapas/curadoria.py:51-52,76-77` (`_gerar_skeletons`,
`aplicar_sobrescritas`) usam `prompts.ampulheta` em vez de
`prompts.progresso_paralelo` — apesar do Port `OrquestradorDeTabelas.
aplicar_sobrescritas` já aceitar o mesmo callback `progresso` usado em
`extrair()`, e `len(tabelas)` já ser conhecido de antemão.

**Correção:** trocar para `progresso_paralelo` nos dois pontos.

### 3.3. Etapa de extração não emite `✓` de sucesso ao concluir

`cli/etapas/extracao.py:165-171` — único dos 4 blocos de operação longa sem
linha de fechamento visual. Também tem duas linhas em branco consecutivas em
vez de uma.

**Correção:** adicionar `✓ N tabela(s) extraída(s).` seguindo o padrão dos
outros três blocos; corrigir espaçamento duplicado.

### 3.4. Seed default de amostragem aleatório

`extractors/comum/seed_efetivo.py:20-22` — gera diff/churn a cada
reextração sem mudança real na fonte.

**Correção (decisão já fechada, ver acima):** trocar para um valor default
fixo (constante nomeada) em vez de gerado por execução — usuário que quiser
variabilidade real continua podendo informar seed explícito no wizard.

## Escopo desta issue

- [ ] `src/ddf/py.typed` (novo) + validação do wheel
- [ ] `domain/ports/orquestrador_de_tabelas.py` — positional-only em
      `aplicar_sobrescritas`
- [ ] `pyproject.toml` — `tests` no escopo do `mypy --strict`
- [ ] `docs/system_design_doc.md` — lista de Ports corrigida; política de
      extensão de `EstrategiaDeAmostragem`/`OrquestradorDeTabelas`
- [ ] Decisão + ação sobre calibração de limiares (valor definitivo ou issue
      formal)
- [ ] `extractors/comum/particionamento.py` (novo) — `particoes_de_blocos`/
      `particionar_faixas_exaustivas` unificados
- [ ] `generators/comum/` — `colunas_em_fk_composta` movido pra lá
- [ ] Reclassificação de categoria nos 3 testes de Gerador
- [ ] `wizard.py`/`analise.py` — sinal de "streaming ativado" reintroduzido
      (ver ponto técnico a confirmar nas Decisões acima)
- [ ] `cli/etapas/curadoria.py` — `progresso_paralelo` em vez de `ampulheta`
      nas duas etapas
- [ ] `cli/etapas/extracao.py` — linha `✓` de sucesso + espaçamento corrigido
- [ ] `extractors/comum/seed_efetivo.py` — seed default fixo
- [ ] `mypy --strict`/`ruff` limpos

## Testes

- [ ] `py.typed`: teste manual de build + inspeção do wheel
- [ ] `aplicar_sobrescritas`: teste de tipagem confirmando que chamada por
      keyword contra o Port passa a ser rejeitada (ou nota de que é só
      checagem estática, sem teste de runtime possível)
- [ ] `particionamento.py`: testes unitários da função unificada cobrindo os
      casos hoje testados separadamente nos dois motores
- [ ] `colunas_em_fk_composta`: teste unitário único em `generators/comum/`,
      remover duplicação de teste dos dois Geradores
- [ ] `cli/etapas/curadoria.py`: teste confirmando `progresso_paralelo`
      chamado com `len(tabelas)` correto
- [ ] `cli/etapas/extracao.py`: teste confirmando linha `✓` emitida com
      contagem correta
- [ ] `seed_efetivo.py`: teste confirmando valor default estável entre
      execuções (mesmo seed sem input do usuário)

## Verificação final

- [ ] `mypy --strict src` + `mypy --strict tests` (se 1.3 entrar neste
      escopo) + `ruff check .` limpos
- [ ] `pytest tests/unit` + `pytest tests/integration` verdes
- [ ] Rodar o wizard manualmente contra um schema real (extração paralela +
      curadoria) para confirmar visualmente os 3 ajustes do Bloco 3

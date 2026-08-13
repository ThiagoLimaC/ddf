# Issue #142 — chore: fecha contrato de extensão, duplicação interna e feedback do wizard antes da v1

## Contexto

Mesma auditoria de fechamento de v1 das #140/#141. Achados sem decisão de
produto pendente — nenhum exige escolher entre alternativas de negócio, só
implementação. Agrupados por afinidade em três blocos: contrato de
extensão/plugin, duplicação interna, e feedback visual do wizard.

## Banca de revisão do plano (antes da implementação)

Arquiteto de Software + Engenheiro de Dados + PO-Revisor + Especialista UX
Terminal (este último só sobre o Bloco 3) revisaram este plano antes de
qualquer código ser escrito. Aprovação com ressalvas dos 4 — achados
incorporados abaixo, mudando 3 itens do escopo original.

- **Item 2.1 (unificar `particoes_de_blocos`/`particionar_faixas_exaustivas`
  em `extractors/comum/`) — removido do escopo, decisão do usuário.** O
  arquiteto apontou que `mariadb/_construcao.py:278-291` já tem docstring
  registrando que essa exata unificação foi avaliada e **rejeitada** no
  passado: Postgres particiona blocos físicos (`ctid`, uniforme por
  construção), MariaDB particiona domínio lógico de PK (uniforme só com PK
  densamente distribuída — gap já sinalizado e adiado pela #126). A
  equivalência é só aritmética (`particoes_de_blocos(T,n) ≡
  particionar_faixas_exaustivas(0,T-1,n)`, confirmado), não estatística.
  Diante desse contexto, o usuário decidiu manter a duplicação intencional —
  2ª vez que essa unificação é avaliada e descartada, agora com decisão
  explícita, não só docstring antiga.
- **Item 2.2 (mover `colunas_em_fk_composta` para `generators/comum/`) —
  removido do escopo, achado bloqueante do arquiteto.** A citação de linha do
  achado original (`dbt/_yaml.py:127-129`) está errada — a função real
  equivalente é `dbt/_testes.py:103-138` (`_referencias_de_fk_composta`), que
  resolve pareamento posicional (`set[tuple[escopo,tabela,coluna]]`), enquanto
  `markdown/_filtros.py:149-163` (`_colunas_com_fk_composta`) resolve só
  participação booleana (`frozenset[str]`) — perguntas diferentes que só
  coincidem em iterar `restricoes_fk_compostas`. `_colunas_com_fk_composta`
  também tem hoje um único call site (`markdown/gerador_markdown.py:56`), não
  atendendo ao próprio critério de admissão de `generators/comum/` ("reusado
  por 2+ Geradores concretos"). Não há duplicação real a resolver.
- **Item 1.5 (calibração de limiares) — mantido nesta issue, decisão do
  usuário.** PO e Engenheiro de Dados recomendaram abrir issue formal
  separada (3ª aparição do compromisso adiado desde #114/#126, benchmarks
  existentes não cobrem a fronteira dos limiares atuais). O usuário optou por
  resolver aqui mesmo assim — ver plano de execução na seção própria abaixo.
- **Item 3.4 (seed default fixo) — decisão mantida, ganha nota técnica.**
  Engenheiro de Dados: seed fixo = mesma fatia física amostrada para sempre,
  não "amostra aleatória reproduzível eventualmente" — se a fatia cair numa
  região não-representativa, o viés nunca é percebido porque a amostra nunca
  muda. Trade-off aceito (ganho de diff estável em Git), mas precisa estar
  documentado, não implícito.
- **Item 3.1 (sinal de streaming) — muda de abordagem.** Nem (a) nem (b) do
  plano original resolviam sem risco de reintroduzir a colisão da #116.
  Recomendação convergente do Engenheiro de Dados e da Especialista UX
  Terminal: separar em duas mudanças independentes — heartbeat visual dentro
  de `progresso_paralelo` (resolve "não travou") + converter o
  `_logger.info` de streaming em `Aviso` anexado ao `Resultado` que
  `extrair_tabela` já devolve (resolve "por quê", corretamente atribuído, sem
  segundo escritor disputando o redraw `\r`).
- **Itens 3.2/3.3 — mesmo objetivo, refinamento de execução.** UX: 3.2 deve
  trocar também o texto do rótulo para o padrão substantivo-resultado já
  usado em `extracao.py` ("Skeletons gerados", não "Gerando skeletons...");
  3.3 não é só inserir a linha `✓`, é reordenar para
  avisos → `✓` → duração (hoje a extração é a única etapa com duração antes
  dos avisos).
- **Item 1.3 (`tests` no mypy --strict) — ganha teto de esforço explícito.**
  PO: confirmar antes de começar que, se sobrar volume não-trivial de erro
  genuíno depois do 1.1 (`py.typed`), o residual vira issue de follow-up, não
  expande esta. Arquiteto confirmou empiricamente 369 erros hoje,
  majoritariamente em cascata do `py.typed` ausente.
- **Itens 1.1, 1.2, 1.4, 2.3 — sem ressalva**, implementação como planejada
  originalmente.

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

**Resolvido — calibração real feita nesta issue** (decisão do usuário,
diferente da recomendação inicial da banca de abrir issue separada — ver
"Banca de revisão do plano" acima). 4 benchmarks novos, marcados
`benchmark` (não rodam no CI padrão), medindo tempo/RSS dos dois lados de
cada fronteira, em 2 perfis de largura de linha (estreito isola o critério
de linhas, largo isola o de bytes), contra Postgres 16 e MariaDB 11 reais
via `testcontainers`:

- `tests/integration/extractors/postgres/test_calibracao_limiares_streaming.py`
- `tests/integration/extractors/mariadb/test_calibracao_limiares_streaming.py`
- `tests/integration/extractors/postgres/test_calibracao_limiares_paralelismo.py`
- `tests/integration/extractors/mariadb/test_calibracao_limiares_paralelismo.py`

**Streaming — valores mantidos (100.000 linhas / 100.000.000 bytes):**
perfil estreito mostra ganho pequeno perto da fronteira (~0% a 70k, ~5-6% a
130k linhas, nos dois motores) — efeito diluído pela base fixa do processo
Python, sem sinal de limiar errado. Perfil largo mostra ganho já grande
**abaixo** do limiar atual (Postgres -49% a 80MB/-56% a 120MB; MariaDB -42%
a 80MB/-48% a 120MB) — limiar de bytes é conservador, não errado: mantém o
custo de streaming (transação aberta, risco de `VACUUM` represado) fora de
tabelas onde o ganho, mesmo grande, ainda não foi comprovado necessário.

**Paralelismo intra-tabela — limiar de LINHAS baixado de 500.000 para
100.000, limiar de BYTES mantido em 500.000.000:**
- Linhas: **correção pós-implementação (banca de revisão do diff, achado
  do engenheiro de dados)** — a 1ª rodada desta calibração testou a
  fronteira do valor antigo (350k/650k, não o valor shipado) por sondas
  ad-hoc não incorporadas ao teste versionado; os testes foram corrigidos
  para medir de fato os pontos 20.000/120.000 (fronteira do valor
  shipado), e a evidência abaixo reflete a rodada corrigida, reproduzível
  a partir do teste commitado. Postgres: custo líquido **negativo** a
  20.000 linhas (0.22x — overhead fixo de coordenar múltiplas conexões
  supera o ganho de paralelizar pouco trabalho), ganho positivo a 120.000
  (1.65x). MariaDB: ganho positivo nos dois pontos (1.45x a 20.000; 4.44x
  a 120.000, efeito dominado por `connectorx` vs. `pymysql` puro no
  caminho sequencial) — assimetria na direção oposta à do limiar de bytes
  abaixo: aqui é o Postgres que só compensa acima da fronteira, não o
  MariaDB. 100.000 fica no meio da faixa observada — conservador para o
  motor que precisa da margem (Postgres), sem custo para o outro (MariaDB
  ganha nos dois pontos testados).
- Bytes: **assimetria real entre motores**, achado não previsto no plano
  original — Postgres ganha na fronteira larga (1.72-1.89x a ~420MB,
  1.89-2.29x a ~580MB, variação entre rodadas), MariaDB não (1.01-1.32x a
  ~420MB, 0.98-1.14x — neutro/levemente pior — a ~580MB). Baixar o limiar
  de bytes beneficiaria só o Postgres, arriscando ativar paralelismo sem
  ganho comprovado em tabelas largas do MariaDB. Sem um limiar por motor
  (mudança estrutural fora do escopo desta calibração), prevalece o valor
  mais conservador — mantido em 500.000.000.

Detalhes completos (tabela de evidências) em `docs/low_level_design.md`
(seção de paralelismo intra-tabela) e `docs/system_design_doc.md` (seção de
streaming via cursor server-side). Código alterado: só
`_LIMIAR_LINHAS_PARALELISMO_INTRA_TABELA` em
`extractors/comum/leitura_paralela_intra_tabela.py` (500_000 → 100_000) —
os outros 3 valores (`_LIMIAR_LINHAS_STREAMING`, `_LIMIAR_BYTES_STREAMING`,
`_LIMIAR_BYTES_PARALELISMO_INTRA_TABELA`) ficam como estavam, agora com
evidência medida em vez de "candidato".

**Fora de escopo, registrado como follow-up:** limiar por motor (não só
por critério) para paralelismo intra-tabela — resolveria a assimetria
Postgres/MariaDB na fronteira de bytes sem sacrificar o ganho do Postgres,
mas exige mudança estrutural (parâmetro extra no dispatch de cada
Extrator) maior que o escopo de uma calibração de valores.

## Bloco 2 — Duplicação interna

### 2.1. ~~Mesmo algoritmo de particionamento duplicado por motor~~ — removido do escopo

`postgres/_construcao.py:104` (`particoes_de_blocos`) e
`mariadb/_construcao.py:276` (`particionar_faixas_exaustivas`) são a mesma
aritmética: `particoes_de_blocos(T, n) ≡ particionar_faixas_exaustivas(0,
T-1, n)`.

~~**Correção:** extrair para `extractors/comum/particionamento.py`.~~
**Decisão final:** não extrair — ver "Banca de revisão do plano" acima. A
equivalência é só aritmética, não estatística (Postgres particiona blocos
físicos, MariaDB domínio lógico de PK); a docstring de
`particionar_faixas_exaustivas` já registrava essa unificação como avaliada
e rejeitada. Duplicação mantida intencionalmente.

### 2.2. ~~`colunas_em_fk_composta` calculado duas vezes~~ — removido do escopo

`markdown/_filtros.py:155-159` e `dbt/_yaml.py:127-129` — mesmo cálculo, dois
estilos. `generators/comum/_metricas.py` já existe como casa pra regra
compartilhada entre Geradores.

~~**Correção:** mover para `generators/comum/`.~~
**Decisão final:** não mover — achado bloqueante do arquiteto (ver "Banca de
revisão do plano" acima). A citação de linha original estava errada; as
duas funções resolvem perguntas diferentes (participação booleana vs.
pareamento posicional) e `_colunas_com_fk_composta` tem um único call site
hoje, não atendendo ao critério de admissão de `generators/comum/`. Não há
duplicação real.

### 2.3. Categoria de teste declarada ≠ conteúdo, nos 3 Geradores

`test_gerador_markdown.py:159`, `test_gerador_dbt.py:311`,
`test_gerador_contexto_de_ia.py:126` — teste de erro (`Falha` ao não
conseguir escrever em disco) dentro de `class TestFeliz`. Nenhum dos três
arquivos tem `class TestErro`.

**Correção:** reclassificar nos três arquivos.

## Bloco 3 — Feedback visual do wizard

### 3.1. ~~`_configurar_logging()` nunca chamada — regressão silenciosa da própria #116~~ — feito

`wizard.py:51-63,80-92` — a função existia, era testada isoladamente, mas a
chamada foi removida no commit `eaf0da8` (evitar log colidindo com redraw
`\r` da barra de progresso) sem documentar a decisão. Três fontes (doc,
docstring, código) descreviam comportamentos diferentes; o cenário de
origem da #116 (tabela outlier ativando streaming) não emitia nenhum
sinal.

**Correção aplicada (abordagem revisada pela banca, ver "Achados da banca"
acima — não reativa `_configurar_logging()` para este caso):**
- **"Não travou":** `prompts.py::progresso_paralelo` virou context manager
  (`@contextmanager`, `Generator[Callable[[str], None], None, None]`) com
  thread própria de heartbeat (`_INTERVALO_HEARTBEAT_SEGUNDOS = 0.3`),
  mesmo padrão de `ampulheta`/`barra_indeterminada` — redesenha o spinner
  (`_QUADROS_AMPULHETA`) periodicamente mesmo sem nenhum item concluir; a
  barra em si só avança em item de fato concluído. Callback e heartbeat
  agora escrevem na tela em threads diferentes, serializadas por um
  `threading.Lock`. Call site (`cli/etapas/extracao.py::extrair`) migrado
  de `progresso = prompts.progresso_paralelo(...)` para
  `with prompts.progresso_paralelo(...) as progresso:`.
- **"Por quê":** `_logger.info("streaming ativado...")` em
  `extractors/postgres/extrator_postgres.py` e
  `extractors/mariadb/extrator_mariadb.py` substituído por `Aviso` anexado
  à lista `avisos` já existente no escopo de `extrair_tabela`, subindo
  agregado no `Resultado` — exibido por `ou_sair`/`exibir_avisos`
  (`avisos.py`), mesmo canal já usado para o viés de cluster de
  `AmostragemPorFaixa`. Nenhum segundo escritor toca a região de tela do
  `progresso_paralelo`, eliminando a causa raiz da #116 por design (não só
  reativando o log antigo).
- `_configurar_logging()` **não foi removida** — outros `_logger.info`
  (paralelismo intra-tabela, nos dois Extratores) continuam usando o mesmo
  mecanismo; só o exemplo na docstring (`wizard.py`) e no teste
  (`test_wizard.py`) foi trocado de "streaming ativado" para "paralelismo
  intra-tabela ativado", que é o caso que ainda se aplica.
- `docs/system_design_doc.md` (seção streaming, issue #114) corrigido: não
  descreve mais "logado, handler configurado pelo wizard" — descreve o
  `Aviso` e por que a abordagem antiga foi trocada (colisão com o redraw
  `\r`, causa raiz da #116).
- Testes: `test_extrator_postgres.py`/`test_extrator_mariadb.py`
  (`test_tabela_acima_do_limiar_de_linhas_usa_cursor_nomeado_em_lotes`/
  `..._usa_sscursor_em_lotes`) migrados de `caplog` para inspecionar
  `resultado.avisos`; `test_prompts.py` migrado para `with ... as callback`
  nos dois testes existentes de `progresso_paralelo`, mais 2 testes novos
  (heartbeat encerra a thread ao sair do bloco; heartbeat redesenha sem
  nenhum item concluído).

### 3.2. ~~Curadoria paralela usa spinner indeterminado, não barra real~~ — feito

`cli/etapas/curadoria.py:51-52,76-77` (`_gerar_skeletons`,
`aplicar_sobrescritas`) usavam `prompts.ampulheta` em vez de
`prompts.progresso_paralelo` — apesar do Port `OrquestradorDeTabelas.
aplicar_sobrescritas` já aceitar o mesmo callback `progresso` usado em
`extrair()`, e `len(tabelas)` já ser conhecido de antemão.

**Correção aplicada:** os dois pontos migraram para
`with prompts.progresso_paralelo(...) as progresso:`, passando `total=
len(tabelas)` e `progresso=progresso` para `aplicar_sobrescritas`. Rótulos
no padrão substantivo-resultado (achado da especialista-ux-terminal, ver
"Achados da banca" acima), não gerúndio: "Skeletons gerados" (era "Gerando
skeletons..."), "Sobrescritas aplicadas" (era "Aplicando sobrescritas...")
— alinhado ao rótulo já usado em `extracao.py` ("Tabelas extraídas"). As
três barras determinadas do wizard agora falam a mesma língua. Espaçamento
pós-`with` mantido em 1 `print()` (não 2) — mesma correção da 3.3 abaixo:
`progresso_paralelo` desenha 3 linhas mas a última já termina sem `\n`, um
único `print()` fecha a linha antes do próximo conteúdo, sem duplicar
espaço em branco.
Testes: `test_gerar_skeletons_usa_progresso_paralelo_com_total_de_tabelas` +
`test_aplicar_sobrescritas_usa_progresso_paralelo_com_total_de_tabelas`
(novos, `TestBorda`) confirmam `"(0/N)"` com o rótulo certo via `capsys`.

### 3.3. ~~Etapa de extração não emite `✓` de sucesso ao concluir~~ — feito

`cli/etapas/extracao.py:165-171` — único dos 4 blocos de operação longa sem
linha de fechamento visual. Também tinha duas linhas em branco consecutivas
em vez de uma.

**Correção aplicada:** `extrair()` passou a seguir a sequência-alvo definida
no plano (avisos → ✓ → duração):

```python
print()
tabelas = ou_sair(resultado)
prompts.imprimir_destacado(f"✓ {len(tabelas)} tabela(s) extraída(s).", ...)
print(f"duração: {time.monotonic() - inicio:.0f}s")
return tabelas
```

Espaçamento corrigido de 2 `print()` para 1 — a redundância vinha de um
resquício da versão antiga de `progresso_paralelo` (não context manager).
**Achado durante a implementação:** a mesma correção de espaçamento (2→1
`print()`) também se aplicava a `cli/etapas/curadoria.py` — copiei o padrão
antigo (2 prints) ao migrar a 3.2 antes de notar que era o mesmo bug;
corrigido junto, nos dois pontos de `curadoria.py` (ver seção 3.2 acima).
Teste novo: `test_extrair_emite_avisos_antes_do_sucesso_e_a_duracao_por_ultimo`
(`TestBorda`) — intercepta `questionary.print` e `builtins.print` num único
evento ordenado, confirma `indice_aviso < indice_sucesso < indice_duracao`.

### 3.4. ~~Seed default de amostragem aleatório~~ — feito

`extractors/comum/seed_efetivo.py:20-22` — gerava diff/churn a cada
reextração sem mudança real na fonte.

**Correção aplicada:** `_SEED_PADRAO = 142`, constante global do `ddf`
(não específica de uma extração), substitui o antigo
`random.randint(0, _SEED_MAXIMO)`. Docstring do módulo documenta o
trade-off apontado pelo engenheiro de dados na banca: seed fixo dá diff
estável em Git, mas é sempre a mesma fatia física da tabela — se essa fatia
for não-representativa, o viés nunca é percebido porque a amostra nunca
varia entre execuções para expor a diferença. Rotação ocasional é
responsabilidade do usuário via seed explícito. Mesma nota replicada em
`docs/system_design_doc.md`, seção `MetadadosDeAmostra` (item que ficara
pendente do 1.4). Docstring de `postgres/_construcao.py:montar_consulta_amostra`
também ajustada (`sorteia` → `preenche com o default`, não é mais aleatório).
Teste `test_seed_ausente_gera_um_valor_inteiro` (assumia aleatoriedade)
substituído por `test_seed_ausente_usa_o_padrao_fixo_do_ddf` +
`test_seed_ausente_e_estavel_entre_chamadas`.

## Escopo desta issue

- [x] `src/ddf/py.typed` (novo) + validação do wheel
- [x] `domain/ports/orquestrador_de_tabelas.py` — positional-only em
      `aplicar_sobrescritas` (+ mesmo padrão espelhado na implementação
      concreta `OrquestradorParalelo`)
- [x] `pyproject.toml` — `tests` no escopo do `mypy --strict` (369 erros
      medidos após `py.typed`, todos corrigidos — ver commits
      `test(protocols)`/`test(tipagem)`; nenhum residual virou follow-up)
- [x] `docs/system_design_doc.md` — lista de Ports corrigida (5); política de
      extensão de `EstrategiaDeAmostragem`/`OrquestradorDeTabelas`
      documentada. Nota sobre viés de seed fixo em `MetadadosDeAmostra`
      adicionada junto com o item 3.4 (feito, ver seção 3.4)
- [x] ~~`extractors/comum/particionamento.py` (unificação)~~ — removido do
      escopo pela banca de revisão do plano, decisão do usuário (ver seção
      "Banca de revisão do plano" acima)
- [x] ~~`generators/comum/` — mover `colunas_em_fk_composta`~~ — removido do
      escopo, achado bloqueante do arquiteto: não é duplicação real (ver
      seção "Banca de revisão do plano" acima)
- [x] Reclassificação de categoria nos 3 testes de Gerador
- [x] Calibração real de limiares de streaming/paralelismo intra-tabela via
      `testcontainers` (Postgres 16 + MariaDB 11), medindo tempo/RSS nos dois
      lados de cada fronteira, 2 perfis de largura de linha (estreita/larga
      com TOAST) — resultado completo na seção 1.5 acima
- [x] `prompts.py::progresso_paralelo` — heartbeat visual (thread própria,
      mesmo padrão de `ampulheta`/`barra_indeterminada`) para "não travou"
- [x] `extractors/postgres/extrator_postgres.py` +
      `extractors/mariadb/extrator_mariadb.py` — sinal de "streaming
      ativado" migrado de `_logger.info` para `Aviso` no `Resultado`
      (abordagem revisada pela banca, ver seção acima — substitui a ideia
      original de aninhar `barra_indeterminada`)
- [x] `cli/etapas/curadoria.py` — `progresso_paralelo` em vez de `ampulheta`
      nas duas etapas, rótulos no padrão substantivo-resultado
- [x] `cli/etapas/extracao.py` — linha `✓` de sucesso, reordenada
      (avisos → ✓ → duração), espaçamento corrigido
- [x] `extractors/comum/seed_efetivo.py` — seed default fixo + docstring do
      trade-off de viés estatístico
- [x] `mypy --strict`/`ruff` limpos (183 arquivos, 674 testes `unit` verdes
      após cada etapa do Bloco 3)

## Testes

- [x] `py.typed`: teste manual de build + inspeção do wheel (`zipfile`,
      `ddf/py.typed` confirmado presente no `.whl`)
- [x] `aplicar_sobrescritas`: sem teste de runtime dedicado — é checagem
      estática (`mypy --strict`), não há como testar positional-only em
      runtime; todos os call sites reais já eram posicionais, confirmado por
      grep antes da mudança
- [x] Calibração de limiares: benchmark versionado (marcado `benchmark`, fora
      do CI padrão) cobrindo Postgres e MariaDB, 2 perfis de largura de
      linha, tempo/RSS nos dois lados de cada fronteira
- [x] `progresso_paralelo`: `test_progresso_paralelo_encerra_a_thread_de_heartbeat_ao_sair`
      (thread desliga ao sair do `with`, mesmo padrão de `ampulheta`) +
      `test_progresso_paralelo_heartbeat_redesenha_sem_nenhum_item_concluido`
- [x] Extratores: `test_tabela_acima_do_limiar_de_linhas_usa_cursor_nomeado_em_lotes`
      (Postgres) / `..._usa_sscursor_em_lotes` (MariaDB) confirmam `Aviso`
      com a mensagem esperada em `resultado.avisos`, não mais log
- [x] `cli/etapas/curadoria.py`: `test_gerar_skeletons_usa_progresso_paralelo_com_total_de_tabelas`
      + `test_aplicar_sobrescritas_usa_progresso_paralelo_com_total_de_tabelas`
      confirmam `progresso_paralelo` chamado com `len(tabelas)` correto
- [x] `cli/etapas/extracao.py`: `test_extrair_emite_avisos_antes_do_sucesso_e_a_duracao_por_ultimo`
      confirma linha `✓` emitida com contagem correta, na ordem correta
      (avisos → ✓ → duração)
- [x] `seed_efetivo.py`: `test_seed_ausente_usa_o_padrao_fixo_do_ddf` +
      `test_seed_ausente_e_estavel_entre_chamadas` — valor default fixo e
      estável entre execuções sem input do usuário

## Verificação final

- [x] `mypy --strict src` + `mypy --strict tests` (com teto de esforço
      acordado — erro residual não-trivial após 1.1 vira issue de
      follow-up) + `ruff check .` limpos — 183 arquivos, 0 erros
- [x] `pytest tests/unit` (674 testes) + `pytest tests/integration`
      (79 testes, 17 `benchmark` deselecionados por padrão) verdes
- [x] Rodado o cenário real da #116 (3 tabelas pequenas + 1 outlier de
      ~120MB ativando streaming, todas em paralelo) via
      `Postgres 16 testcontainer` + `OrquestradorParalelo`/`ExtratorPostgres`
      reais, chamando `cli/etapas/extracao.py::extrair` diretamente (mesma
      função usada pelo wizard) — não um fake. Confirmado: contagem parada
      em "(3/4)" por vários frames com o spinner do heartbeat girando
      (`⠸→⠼→⠴→⠦`), sem parecer travado; `Aviso` de streaming exibido depois
      da barra terminar, sem nenhuma colisão/garbage no `\r`; ordem final
      avisos → `✓ 4 tabela(s) extraída(s).` → `duração: 1s`, confirmando a
      #116 resolvida por design, não só no teste unitário isolado.
- [x] Benchmarks de calibração rodados e resultado (valores confirmados ou
      ajustados) registrado nesta issue, com a medição como evidência — ver
      seção 1.5 acima

## Banca de revisão do diff (pós-implementação)

Com a implementação completa e commitada, convoquei a mesma banca (arquiteto-
de-software, engenheiro-de-dados, po-revisor, especialista-ux-terminal) para
revisar o **diff real** (`git diff <merge-base com development>`), em modo
somente-leitura. Aprovação com ressalvas — 2 achados de alto impacto e 1 de
convenção, corrigidos nesta rodada; nitpicks registrados sem ação (ver
abaixo).

**[Corrigido — Engenheiro de Dados] Evidência de calibração do paralelismo
intra-tabela não era reproduzível.** A 1ª rodada da calibração (seção 1.5
acima) citava evidência medida a 100.000/20.000 linhas, mas os testes
commitados ainda mediam a fronteira do valor **antigo** (350k/650k) — os
números 100k/20k vieram de sondas ad-hoc da sessão, nunca incorporadas ao
teste versionado. Corrigido: `test_calibracao_limiares_paralelismo.py`
(Postgres e MariaDB) agora medem 20.000/120.000 linhas de fato; docstrings
desatualizadas (citavam `500_000` como valor "hoje" em produção) corrigidas.
Evidência real recoletada e registrada na seção 1.5 acima e em
`docs/low_level_design.md` — revela uma assimetria não descrita antes:
Postgres tem custo negativo a 20k (0.22x), MariaDB já ganha nesse ponto
(1.45x) — direção oposta à assimetria do limiar de bytes (lá é o MariaDB que
não ganha). Decisão de manter 100.000 como limiar único (motor-agnóstico) se
sustenta: conservador para o motor que precisa da margem (Postgres), sem
custo para o outro.

**[Corrigido — PO + UX, convergente] Texto do wizard sobre seed ficou
enganoso.** `cli/registro/estrategias.py:76,133` — o prompt "deixe em branco
para aleatório" não foi tocado por esta issue, mas o comportamento mudou
(seed fixo, não mais aleatório) — único ponto onde o usuário final vê esse
comportamento em tempo real. Corrigido para "deixe em branco para usar o
padrão fixo do ddf".

**[Corrigido — Arquiteto] `_SEED_PADRAO` coincidia com o número da issue.**
O valor escolhido (142) era literalmente o número desta issue — não é uma
citação em docstring (já proibida pela convenção), mas uma codificação do
número da issue num valor de produção. Trocado para um valor arbitrário sem
relação com a issue.

**[Corrigido — Arquiteto] Docstrings dos 4 arquivos de benchmark citavam
"(issue #142)".** Violação da regra "docstring nunca cita número de issue" —
removido.

**Achados registrados sem ação** (nitpicks, não bloqueiam):
- Teste `test_progresso_paralelo_com_total_mostra_fracao` depende de timing
  de thread sem sincronização explícita (estável em 20/20 execuções locais).
- Canal de sinal inconsistente: "streaming ativado" virou `Aviso`, mas
  "paralelismo intra-tabela ativado" continua em `_logger.info`, no mesmo
  Extrator.
- Falta critério operacional explícito de quando rodar com seed explícito
  (a doc explica o trade-off, não orienta a ação).
- Pequena janela cosmética no heartbeat (spinner pode redesenhar 1 frame a
  mais antes de `parar.set()` ser observado) — imperceptível, sem
  duplicação real de texto.
- Rótulos particípio-passado ("Skeletons gerados (0/N)") no 1º frame — fricção
  pré-existente de `extracao.py`, não regressão deste diff.

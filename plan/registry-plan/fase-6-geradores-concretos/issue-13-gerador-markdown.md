# Issue #13 — feat: GeradorMarkdown

## Decisões tomadas na discussão prévia (antes de implementar)

Banca acionada sobre a especificação (Arquiteto de Software + Engenheiro de
Dados + PO), como na #11 — antes de qualquer código. Veredito: **Aprovado
com ressalvas** (Arquiteto e Engenheiro de Dados), **Aprovado** (PO, escopo
bate com `plan/tasks.md`/PRD sem scope creep).

> **Separar renderização pura de escrita em disco (Arquiteto).** Escrever
> arquivo é o único ponto de I/O do Adapter; tudo o mais deveria ser função
> pura, testável sem `tmp_path`. **Decisão:** `_escrever_arquivo` isolado;
> demais funções recebem dado de domínio e devolvem `str`/`dict`, sem
> tocar disco.

> **`TipoDeDado` deveria renderizar com precisão real, não só `categoria`
> (Engenheiro de Dados).** `NUMERIC`/`VARCHAR`/`CHAR`/`TIMESTAMP`/`ENUM`
> já carregam precisão/escala/tamanho — mostrar só "VARCHAR" sem tamanho é
> descartar informação que já existe no domínio. **Decisão:**
> `_formatar_tipo` cobre os 5 grupos de atributo (`NUMERIC(p,s)`,
> `VARCHAR(n)`, `CHAR(n)`, `TIMESTAMP WITH TIME ZONE`, `ENUM(...)`).

> **Tamanho da amostra (N de M) só no rodapé não é suficiente (Engenheiro
> de Dados).** Rodapé isolado é o padrão que leva a citar `percentual_nulo`
> como fato absoluto quando N amostrado ≪ M total. **Decisão:** amostra
> visível também no corpo do documento (bloco "Fatos extraídos"), não só
> no rodapé.

> **Descartado por ora: selo de "estimado" por célula e sinal derivado de
> "candidato a chave" (Engenheiro de Dados).** Um sinal combinado
> nulo≈0%+único≈100% seria uma métrica nova (Value Object), não lógica de
> apresentação do Gerador — fere a regra "Métricas como Value Objects" do
> `CLAUDE.md`. **Decisão:** registrado como sugestão para um Analisador
> futuro, fora do escopo de #13.

`docs/low_level_design.md` (seção `GeradorMarkdown`) descrevia o contrato;
as decisões acima resolvem lacunas de apresentação que a especificação não
detalhava.

## Escopo desta issue

- [x] `infrastructure/adapters/generators/gerador_markdown.py` —
      `GeradorMarkdown(Gerador)`: `requer = [MetricasBaseColuna,
      MetricasBaseTabela]`; um `.md` por tabela em `<destino>/<escopo>/
      <tabela>.md` + `index.md` geral
- [x] Renderização via templates Jinja2 (`generators/templates/
      tabela.md.jinja2`, `index.md.jinja2`) — filtros Python registrados
      (`escapar`, `formatar_tipo`, `marcadores_de_chave`, `completude`,
      `linha_qualidade`, `secoes_valores_frequentes`), template só
      interpola/orquestra, nenhuma lógica de negócio no `.jinja2`
- [x] Nota de rodapé com `MetadadosDeAmostra` (estratégia, N amostrado, M
      total) + tamanho de amostra também visível no corpo
- [x] `scripts/prototipo_wizard_mariadb.py` conecta o `GeradorMarkdown`
      real (pedido explícito do usuário, fora do escopo original da issue
      mas dentro do espírito de "provar contra dado real antes do wizard
      da fase 7")
- [x] `mypy --strict src` (47 arquivos, 0 erros) e `ruff check .` limpos

## Testes

- [x] `tests/unit/infrastructure/adapters/generators/` (9 testes):
      caminho feliz (2 tabelas, 2 escopos, `index.md` ordenado); erro de
      disco (`Falha` com o path); tabela sem `papel_de_negocio` (`Aviso`);
      métrica ausente (placeholder `"N/D"`, sem crash); valor com `|`
      escapado; mínimo/máximo suprimidos para categoria textual e para
      `UNKNOWN`; coluna PK recebe nota em Valores frequentes; coluna 100%
      nula recebe nota em vez de ser omitida em silêncio
- [x] Verificação completa: `pytest` (241 passed), `mypy --strict src` (47
      arquivos, 0 erros), `ruff check .` sem erros

## Correções em componentes de issues anteriores (achadas testando com dado real)

Rodar o protótipo contra um MariaDB real (dataset tipo AdventureWorks)
expôs dois bugs pré-existentes no `AnalisadorDeMetricasDeColuna` (#11), não
no `GeradorMarkdown` — corrigidos nesta branch porque bloqueavam a
validação manual da issue, com teste de regressão em
`test_analisador_de_metricas_de_coluna.py`:

> **`pl.Series.min()/max()/n_unique()` levantam `InvalidOperationError` em
> dtype `Object`.** `Object` é o fallback do Polars para tipos Python que
> não mapeia nativamente — `uuid.UUID` (coluna UUID) e `memoryview`
> (coluna `bytea` via `psycopg2`) caem nele. Uma única coluna desse tipo
> derrubava o Analisador inteiro. **Correção:** `_normalizar_serie_objeto`
> stringifica a série antes de qualquer operação, restaurando o
> comportamento de uma coluna `Utf8` normal.

> **`str()` puro sobre `memoryview` produz endereço de memória, não dado
> útil.** `str(memoryview(...))` gera `<memory at 0x7f...>` — muda a cada
> execução, inútil num artefato versionado em Git. **Correção:**
> `_representar_valor_objeto` trata `bytes`/`bytearray`/`memoryview` como
> `"[dado binário, N bytes]"`; qualquer outro tipo (`uuid.UUID`) continua
> usando `str()`, que já produz texto útil.

## Achados da banca de revisão (pós-implementação, contra artefato real)

Diferente da #12, esta issue teve **várias rodadas** de revisão contra o
`.md` real gerado de um banco MariaDB, não só contra fixtures — o usuário
pediu explicitamente opinião do Engenheiro de Dados e do Arquiteto em
pontos específicos ao longo do trabalho.

> **Bug de correção: PK+FK simultâneas perdiam a marcação de FK
> (Engenheiro de Dados).** `_renderizar_linha_de_coluna` usava `if
> chave_primaria / elif chave_estrangeira` — uma coluna PK+FK ao mesmo
> tempo (padrão real de "shared primary key", ex. `BusinessEntityID` no
> AdventureWorks) mostrava só `PK`, descartando a referência. O domínio
> (`ColunaAnalisada`) permite os dois `True` simultâneos; o renderer não
> respeitava isso. **Corrigido:** `_marcadores_de_chave` concatena
> `"PK, FK → ..."` em vez de `if/elif` exclusivo.

> **Min/máx de VARCHAR usa ordenação lexicográfica, não numérica
> (Engenheiro de Dados, validado empiricamente com Polars local).** Uma
> coluna `nationalidnumber` (ID numérico armazenado como texto) mostrava
> "mínimo"/"máximo" sem significado de negócio nenhum. **Corrigido:**
> `_CATEGORIAS_SEM_MINIMO_E_MAXIMO` suprime min/max (mostra `"—"`) para
> VARCHAR/CHAR/TEXT/UUID/ENUM/SET/BOOLEAN/UNKNOWN — todas categorias em
> que a ordenação do Polars não corresponde a ordem de negócio.

> **Redesenho de UI/UX: uma tabela só de 10 colunas com "Valores
> frequentes" embutido é ilegível (Engenheiro de Dados).** Célula com
> ~250-300 caracteres força scroll horizontal no GitHub e quebra
> completamente em editores de texto puro. **Corrigido (versão "radical"
> aprovada pelo usuário):** tabela de Colunas vira só catálogo (Nome/Tipo/
> Chave/Papel de negócio); estatísticas viram tabela própria "Qualidade
> dos dados"; valores frequentes viram subseção por coluna, fora de
> qualquer tabela larga.

> **Arquivo `gerador_markdown.py` virou o maior do projeto — quase 400
> linhas (usuário, banca do Arquiteto acionada para resolver).**
> Autorização explícita para consultar documentação oficial do
> Python/Jinja2. **Decisão do Arquiteto, com precedente na doc oficial do
> Jinja2:** passar os modelos de domínio direto pro contexto do template
> (`foo.bar` no Jinja tenta `getattr` antes de `dict`) e migrar formatação
> trivial para filtros Jinja registrados (`environment.filters` é
> mutável e seguro de popular antes do primeiro template carregar) — só
> mantendo como função Python nomeada a lógica com ramificação real
> (`_linha_qualidade`, `_secoes_valores_frequentes`), nunca espalhada em
> `{% if %}` no template. **Resultado:** 374 → 303 linhas, sem quebrar
> nenhum teste existente (todos são caixa-preta, verificam o Markdown
> renderizado).

> **Achados do usuário testando manualmente contra dado real (não da
> banca formal):** dado binário (`bytea`) virando endereço de memória —
> ver seção anterior; colunas PK sem aviso na seção de Valores frequentes
> (contagem 1 em quase todo valor, sem sinal analítico) — corrigido com
> nota condicional no template; colunas 100% nulas sendo omitidas em
> silêncio da seção de Valores frequentes (parecia bug de omissão, não
> fato sobre o dado) — corrigido com nota explícita em vez de pular a
> coluna.

## Pendências para próximas issues (não resolvidas aqui)

- **Issue #44** (`feat: NOT NULL e UNIQUE reais do schema, além de PK/FK`)
  — mapeamento feito com o Engenheiro de Dados: hoje `percentual_nulo`
  é métrica de amostra, não prova de restrição `NOT NULL` real; `UNIQUE`
  reaproveitaria o mesmo padrão de captura já usado para PK/FK. Toca os
  três Bounded Contexts e os dois Extratores — maior que uma issue de
  Gerador, por isso não entrou aqui.
- **Corte de cardinalidade em `valores_frequentes`** (Engenheiro de
  Dados): colunas com `percentual_unico` ~100% ainda listam até 10
  valores com contagem 1 — ruído, não sinal. O nota de PK cobre o caso
  mais comum (PK é sempre ~100% única), mas uma coluna não-PK de alta
  cardinalidade continua sem aviso. Sugestão registrada: reaproveitar o
  mesmo limiar (`percentual_unico < 10.0`) que o `GeradorDbt` (#14) vai
  usar para sugerir `accepted_values`.
- **Novo Analisador de estatísticas descritivas** (média, moda, desvio
  padrão amostral, quartis p25/p50/p75) para colunas numéricas — sugerido
  pelo Engenheiro de Dados como o próximo Analisador natural (fecha lacuna
  real vs. dbt docs/DataHub/Great Expectations). Armadilhas já mapeadas,
  a resolver na especificação antes de implementar: fixar
  `interpolation="linear"` nos quantis (default do Polars é `"nearest"`,
  diverge do próprio `median()` da lib); `ddof=1` explícito no desvio
  padrão (amostral); moda tratada como "não significativa" quando a
  contagem máxima empatar em 1; threshold de amostra mínima próprio para
  quartis (diferente do `_TAMANHO_AMOSTRA_MINIMO_AVISO=100` da #11);
  escopo v1 estritamente numérico, sem estender a `DATE/TIME/TIMESTAMP`.
- **`detectar_formato` (#11) só cobre padrões brasileiros** (CPF/CNPJ/CEP/
  telefone + email) — evidenciado ao rodar contra um dataset não-BR
  (AdventureWorks/MariaDB): toda coluna VARCHAR do protótipo voltou
  `formato_detectado=None`. Fora do escopo do Gerador (é decisão do
  Analisador #11); registrado aqui porque só ficou visível testando o
  artefato final.
- **`_formatar_tipo`/`_CATEGORIAS_COM_*`** continuam só em
  `gerador_markdown.py` — não extraídos para módulo compartilhado
  (abstração prematura com um único consumidor). Revisitar quando
  `GeradorDbt` (#14) existir: se ele reaproveitar a mesma formatação de
  tipo (tem cast SQL próprio, então pode não precisar) ou tiver a própria
  representação, decide se vale extrair.
- Quebrar `gerador_markdown.py` em subdiretório (`generators/markdown/`)
  — opção de último recurso levantada pelo usuário, não precisou ser
  usada; revisitar só se o arquivo voltar a crescer significativamente.
- Wizard real interativo (fase 7, issue #16) continua não implementado;
  `scripts/prototipo_wizard_mariadb.py` cobre só validação manual
  não-interativa do pipeline ponta a ponta.

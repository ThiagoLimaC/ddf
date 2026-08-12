# Issue #34 — feat: generaliza vocabulário relacional (schema → escopo) e adiciona listar_escopos

## Decisões tomadas na discussão prévia (antes de implementar)

> **Vazamento não é só do `ExtratorPostgres`.** `nome_schema` estava presente
> nos três Bounded Contexts (`TabelaExtraida`, `TabelaCurada`,
> `TabelaAnalisada`) e nas Ports (`Extrator`, `OrquestradorDeTabelas`), não só
> no adapter concreto. A própria issue #10 já tinha registrado isso como
> pendência não bloqueante
> (`plan/registry-plan/issue-10-sobrescrita-e-orquestrador.md:230-234`),
> adiada até a "primeira fonte não-relacional". Antecipado agora porque
> Analisadores, Geradores e o wizard da CLI (as próximas camadas que
> herdariam esse vocabulário) ainda não existem.

> **Novo nome: `escopo`, não `namespace`.** Cogitado `namespace` (mais
> autoexplicativo, empréstimo comum mesmo em PT-BR) e `agrupamento`. Decisão:
> `escopo` — mantém 100% português, consistente com o resto do modelo
> (`nome_tabela`, `chave_primaria`, etc.). `namespace` seria o primeiro campo
> Pydantic em inglês do projeto, sem necessidade real de sê-lo.

> **Contrato de `Falha` da Port deixa de mandar string exata.** O
> `low_level_design.md` documentava `Falha("Schema 'x' ou tabela 'y' não
> encontrada.")` como comportamento esperado de qualquer `Extrator`. Isso
> amarra vocabulário Postgres no contrato da Port. Decisão: a Port descreve
> só o comportamento (Falha clara nomeando o que não foi encontrado); cada
> `Extrator` concreto escreve na própria língua. `ExtratorPostgres` mantém a
> palavra "Schema" — é vocabulário correto pra quem usa Postgres, isso não
> muda.

> **`nome_escopo` continua `str` simples, sem Value Object hierárquico —
> decisão que será testada, não presumida.** Avaliado (e descartado por ora)
> um Value Object de hierarquia multi-nível (catálogo→schema→tabela).
> Descartada a justificativa original de "adiar por falta de uma segunda
> fonte real pra validar" — em vez disso, a issue #35 (`ExtratorMariaDB`)
> constrói essa segunda fonte de propósito, especificamente pra responder se
> `str` basta ou se a estrutura hierárquica é necessária de verdade. Ver
> `plan/registry-plan/issue-35-extrator-mariadb.md` quando existir.

> **`listar_escopos()` novo no `Extrator` Port.** Resolve o gap que
> `scripts/prototipo_wizard.py` (não commitado) contornava com uma query SQL
> direta contra `information_schema.schemata`, por falta desse método no
> Port. Mesmo padrão pool/semáforo dos outros dois métodos do
> `ExtratorPostgres`.

## Escopo desta issue

- [x] `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada` — `nome_schema` → `nome_escopo`
- [x] `BancoCurado`/`BancoAnalisado` — `_valida_tabelas_unicas` usa `(nome_escopo, nome_tabela)`
- [x] `Extrator` (Port) — `schema` → `escopo` em `listar_tabelas`/`extrair_tabela`
- [x] `Extrator` (Port) — novo método `listar_escopos() -> Resultado[list[str]]`
- [x] `Extrator` (Port) — docstring do contrato de `Falha` generalizada
      (na prática o Port nunca mandou a string exata no próprio arquivo — só o
      `low_level_design.md` fazia isso em prosa; segue pendente só lá, no
      item de Documentação abaixo)
- [x] `OrquestradorDeTabelas` (Port) — `schemas` → `escopos` em `extrair`
- [x] `ExtratorPostgres` — implementa `listar_escopos` via `information_schema.schemata`
      (exclui `information_schema`/`pg_catalog`/`pg_toast`/`pg_temp_%`/`pg_toast_temp_%`, mesma lista do protótipo)
      > **Decisão (revista durante a implementação):** dentro do `ExtratorPostgres`, o
      > parâmetro `schema` e a variável local `nome_schema` **não** foram renomeados
      > pra `escopo`/`nome_escopo` — confirmado via teste real com `mypy --strict`
      > que Protocol não exige nome de parâmetro igual ao da implementação concreta
      > (checagem é contra o tipo estático `Extrator` no ponto de uso, não contra a
      > classe concreta). Deixar `schema` aqui é vocabulário correto — é assim que
      > Postgres chama a coisa — e só a Port (`escopo`) e o campo do modelo
      > (`nome_escopo`) precisam do termo neutro. Único ponto que mudou de fato:
      > `TabelaExtraida(nome_escopo=schema, ...)`, porque isso é nome de campo do
      > modelo, não vocabulário livre do adapter.
- [x] `OrquestradorParalelo` — propaga renomeação (`escopos`/`escopo`, `tabela.nome_escopo`)
- [x] `SobrescritaDeTabela` — propaga renomeação (hash, path `overrides/<escopo>/<tabela>.yaml`, mensagens)
      > Ao contrário do `ExtratorPostgres`, aqui a renomeação foi completa — nem
      > `OrquestradorParalelo` nem `SobrescritaDeTabela` são específicos de uma
      > fonte, então não há vocabulário "correto" a preservar internamente; `escopo`
      > é o termo certo em todo o arquivo.
- [x] `mypy --strict src` e `ruff check src` — 0 erros, todo o código de produção da issue está consistente
- [x] Documentação (`low_level_design.md`, `system_design_doc.md`, `prd.md`, `engineer_guidelines.md`,
      `plan/tasks.md`, `plan/topics.md`) — preserva `information_schema`/`pg_catalog`/contrato do dbt/kwarg da polars
      > `low_level_design.md` ganhou documentação nova pro `listar_escopos` (Port +
      > `ExtratorPostgres`) e o contrato de `Falha` de `extrair_tabela` foi
      > generalizado (não manda mais a string exata). `prd.md` teve a linguagem de
      > produto suavizada (schema → "estrutura"/"escopo", conforme o contexto).
      > `plan/topics.md` não precisou de mudança — não desce a esse nível de detalhe.
- [x] Grep final em `docs/`, `plan/`, `src/`, `tests/` confirma: único vocabulário
      "schema" remanescente é `information_schema`/`pg_catalog`/contrato do dbt/kwarg
      da polars, e o vocabulário interno do `ExtratorPostgres` (deliberado, ver nota acima)

## Testes

- [x] Fixtures/fakes renomeados: `test_extraction.py`, `test_curation.py`, `test_analysis.py`,
      `orchestrator/conftest.py`, `test_orquestrador_paralelo.py`, `overrides/conftest.py`,
      `test_extrator_postgres.py`, `cli/test_fontes.py`, `integration/.../test_extrator_postgres_integration.py`
      > `integration/.../conftest.py` não precisou de mudança — só monta `dsn`/`configuracao`,
      > não referencia `nome_schema`/parâmetros de escopo diretamente.
      > Nomes de teste/docstrings dentro dos arquivos específicos de `ExtratorPostgres`
      > (unit + integração) mantiveram "schema" onde descrevem o adapter Postgres —
      > mesma decisão do lote de produção. Em `orchestrator/conftest.py` e
      > `test_orquestrador_paralelo.py` (genéricos, não específicos de Postgres) a
      > renomeação foi completa, incluindo a mensagem de `Falha` fake
      > ("Schema..." → "Escopo...", já que ali não é um Postgres de verdade falando).
- [x] `ExtratorFake` (orchestrator conftest + cli/test_fontes) ganham stub `listar_escopos`
      — Protocol exige todos os membros pro `mypy --strict` aceitar as chamadas onde são passados como `Extrator`
- [x] `listar_escopos` — caminho feliz, erro esperado, borda (unit, mock de cursor/pool)
- [x] `listar_escopos` — teste de integração contra Postgres real (testcontainers), retorna `["public", "vazio"]`
- [x] Verificação completa: `mypy --strict src` (0 erros), `ruff check .` (limpo),
      `pytest tests/unit` (136 passed), `pytest tests/integration` (7 passed, Docker real)

## Banca de revisão multi-agente (PO + Arquiteto de Software + Engenheiro de Dados)

Rodada em duas etapas (revisão independente + reação cruzada) antes do squash
merge. Veredito unânime e estável nas duas rodadas: **Aprovado com
ressalvas**. Nenhum bloqueante. Achados incorporados nesta issue:

- [x] Typo em `docs/prd.md` ("consumir o a estrutura", artigo duplicado —
      introduzido pela própria troca schema→estrutura desta issue) — corrigido.
- [x] `Extrator.listar_tabelas`/`extrair_tabela` e `OrquestradorDeTabelas.extrair`
      ganharam parâmetros positional-only (`/`) — achado do Arquiteto de
      Software: sem isso, `mypy --strict` aceita silenciosamente uma chamada
      por keyword (`extrator.extrair_tabela(escopo=..., tabela=...)`) contra
      uma variável tipada `Extrator`, mas isso quebra em **runtime** com
      `TypeError` sempre que o adapter concreto usa nome de parâmetro
      diferente (caso do `ExtratorPostgres`, que mantém `schema`). Antes desta
      issue, Port e adapter usavam o mesmo nome, então essa lacuna existia mas
      nunca se manifestava — a própria generalização schema→escopo é quem a
      tornou real. Sem call site afetado hoje (os dois usos existentes são
      posicionais), mas o Engenheiro de Dados apontou que é exatamente o
      estilo que o wizard da CLI (próxima issue a consumir essas Ports) tende
      a escrever por clareza. Consenso dos três: não bloqueia este merge, mas
      preferível fechar agora a deixar como dívida.
- [x] Convenção documentada em `docs/engineer_guidelines.md`: parâmetros de
      `Protocol` em `domain/ports/` são positional-only por padrão, para não
      depender que adapters concretos usem o mesmo nome de parâmetro que a Port.

**Ressalva registrada (achado convergente do Arquiteto e do Engenheiro de
Dados):** a issue #35 (`ExtratorMariaDB`) valida só a hipótese **flat**
(schema e database no mesmo nível — verdade em Postgres e MariaDB). Ela não
valida, nem pode por construção, o caso genuinamente hierárquico — o exemplo
concreto mais próximo no radar do projeto é o **SQL Server**, onde a mesma
conexão endereça `outro_database.schema.tabela` (three-part naming) contra
bancos diferentes no mesmo servidor, o que uma modelagem `nome_escopo: str`
mapeada só a schema não capturaria. Snowflake/BigQuery (catálogo/projeto
acima de schema) são exemplos mais extremos, fora do roadmap atual. **Não
ler o resultado da #35 como confirmação de que `str` basta para qualquer
fonte relacional — só confirma que basta para fontes flat.**

## Pendências para próximas issues (não resolvidas aqui)

- ~~**#35 — `ExtratorMariaDB`**: valida se `nome_escopo: str` (flat) basta pra uma segunda fonte flat real —
  ver ressalva acima sobre o que esse resultado cobre e o que não cobre. Ao final da #35, revisitar este
  arquivo com a resposta.~~ **Resolvido pela #35** (ver
  `plan/registry-plan/issue-35-extrator-mariadb.md`): `nome_escopo: str` flat se provou suficiente —
  `ExtratorMariaDB` implementa o `Extrator` Port sem tocar em Extraction/Curation/Analysis, nas outras
  Ports, no `OrquestradorParalelo` ou na `SobrescritaDeTabela`. Confirma só a hipótese **flat** (Postgres e
  MariaDB, cada um a seu jeito), não a hierárquica (SQL Server-like) — essa continua em aberto.
- **CLI wizard**: a banca levantou três pontos que não são lacuna desta issue (que só habilita descoberta
  no Port/Adapter, sem UI), mas precisam virar critério de aceite explícito na issue do wizard, pra não se
  perderem: (1) rótulo do prompt — "Escolher escopo(s)" hoje fixo em `low_level_design.md`, mas o usuário v1
  só conhece Postgres/"schema"; proposta mais concreta trazida na banca é um rótulo dinâmico por `Extrator`
  (ex.: propriedade `rotulo_escopo: str = "schema"` no adapter concreto) em vez de "escopo" fixo; (2) lista
  de escopos sem busca/filtro fica inviável em bancos multi-tenant com muitos schemas; (3) `listar_escopos()`
  retornando `Sucesso([])` (usuário sem privilégio em nenhum schema) precisa virar mensagem acionável na CLI,
  não um checkbox vazio silencioso.
- **Analisadores / Geradores concretos**: issues próprias já existentes no repo — revistas quando chegar a
  vez, já com `escopo` (não `schema`) em mente.

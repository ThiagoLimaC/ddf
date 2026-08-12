# Issue #44 — feat: NOT NULL e UNIQUE reais do schema (além de PK/FK)

## Contexto

Achado da revisão pós-merge da #13 (`GeradorMarkdown`): duas lacunas em
restrições de schema.

1. Nenhuma restrição além de PK/FK é modelada em `ColunaExtraida`/
   `ColunaCurada`/`ColunaAnalisada`.
2. `percentual_nulo` (`MetricasBaseColuna`) é métrica sobre a **amostra**,
   não a população. Uma coluna `NOT NULL` real no schema tem isso garantido;
   uma coluna nullable com nulos esparsos pode sair 100% "limpa" na amostra
   por acaso. As duas situações eram indistinguíveis no artefato gerado.

Mapeamento feito com o Engenheiro de Dados (banca da #13): **NOT NULL real**
e **UNIQUE** são as únicas restrições, além de PK/FK, que trazem valor de
descoberta sem custo desproporcional nos dois motores suportados. CHECK/
DEFAULT ficaram fora — sintaxe diverge estruturalmente entre motores, baixo
valor pra ferramenta de entendimento de dados, não de validação de regra.

## Decisões tomadas na discussão prévia (antes de implementar)

Banca acionada sobre o desenho (Arquiteto de Software + Engenheiro de
Dados), como nas #11/#13, antes de qualquer código. Veredito: **Aprovado com
ressalvas** dos dois — uma das ressalvas revelou um bug real, não hipotético.

> **`nao_nulavel`/`unica` são campos estruturais, não métricas (Arquiteto +
> Engenheiro de Dados).** São fatos do catálogo da fonte, não calculados
> sobre amostra — no mesmo nível epistemológico de `chave_primaria`/
> `chave_estrangeira`. **Decisão:** campos `bool` simples em `ColunaExtraida`/
> `ColunaCurada`/`ColunaAnalisada`, sem novo `MetricaDeColuna`. Respeita
> "Métricas como Value Objects" do `CLAUDE.md` — `MetricasBaseColuna` não
> muda. `GeradorMarkdown` combina o fato estrutural com a métrica amostral
> só na camada de apresentação (mesmo padrão que já cruza `chave_primaria`
> com o aviso de baixo sinal em "Valores frequentes por coluna", desde a
> #13).

> **`is_nullable` de `information_schema.columns` é estável em qualquer
> versão do Postgres — a ressalva original da issue sobre `pg_attribute.
> attnotnull`/PG17 não se aplica (validado empiricamente pelo Engenheiro de
> Dados contra Postgres 16 real).** `is_nullable` sempre refletiu
> `attnotnull` diretamente (é coluna, não constraint); a mudança do PG17
> (NOT NULL catalogado em `pg_constraint`) é sobre uma rota diferente, não
> seguida aqui. **Decisão:** `_COLUNAS_SQL` ganha `is_nullable`, mesma query
> já existente, sem JOIN novo.

> **UNIQUE via `pg_constraint`, como a issue original sugeria, ou via
> `information_schema` no mesmo padrão já usado por PK/FK? Bug real
> encontrado ao testar a segunda opção contra MariaDB real (Engenheiro de
> Dados).** Nomes de constraint no MySQL/MariaDB são escopados **por
> tabela**, não por schema — duas tabelas do mesmo database podem ter uma
> `UNIQUE KEY` com nome idêntico (`UNIQUE(email)` gera constraint `email`
> em qualquer tabela com essa coluna). A query original (mesmo padrão da
> PK, sem `AND kcu.table_name = %s`) produzia uma linha fantasma cruzando
> as duas tabelas, classificando uma coluna UNIQUE real como `unica=False`
> por acidente — reproduzido com dados reais (`pedidos`/`clientes`, ambas
> com `UNIQUE KEY email`). **Decisão:** filtro explícito de `table_name`
> nos dois lados do JOIN no MariaDB.

> **Lacuna real encontrada: índice único solto (`CREATE UNIQUE INDEX` sem
> `ADD CONSTRAINT`) é capturado no MariaDB via `information_schema.
> table_constraints`, mas não no Postgres — mesmo campo `unica`, cobertura
> assimétrica entre motores (Engenheiro de Dados, validado empiricamente
> nos dois motores).** Decisão do usuário: fechar agora, não aceitar a
> assimetria. **Decisão técnica:** Postgres passa a capturar UNIQUE via
> catálogo `pg_index` (desvio deliberado do padrão `information_schema`
> usado por PK/FK) — todo UNIQUE constraint no Postgres é backed por um
> índice em `pg_index`, então uma única query cobre constraint nomeada e
> índice solto. `NOT i.indisprimary` exclui PK sem lógica extra;
> `array_length(i.indkey, 1) = 1` ignora UNIQUE composto.

> **`GeradorDbt` (issue #14, ainda não implementada) tem o mesmo viés
> estatístico que motivou esta issue, com consequência maior (Engenheiro de
> Dados).** `GeradorDbt` sugere `not_null`/`unique` só a partir de métricas
> de amostra — se aceito e versionado, pode virar teste dbt que quebra em
> produção. Decisão do usuário: fora do escopo desta issue; registrado via
> comentário na #14 (não issue nova — #14 já é o lugar certo) após o merge.

## Escopo desta issue

- [x] `domain/model/{extraction,curation,analysis}.py` — `nao_nulavel: bool`
      e `unica: bool` em `ColunaExtraida`/`ColunaCurada`/`ColunaAnalisada`,
      mesmo padrão de `chave_primaria`/`chave_estrangeira`; `unica=True`
      documentado como "unicidade single-column garantida pelo schema" —
      UNIQUE composto (2+ colunas) é deliberadamente não representado
- [x] `ExtratorPostgres`: `is_nullable` na mesma query de colunas; nova
      `_COLUNAS_UNICAS_SQL` via `pg_index`/`pg_class`/`pg_namespace`/
      `pg_attribute`
- [x] `ExtratorMariaDB`: `IS_NULLABLE` na mesma query de colunas; nova
      `_COLUNAS_UNICAS_SQL` via `information_schema.table_constraints`/
      `key_column_usage` com `AND kcu.table_name = %s` (fix da colisão de
      nome) + `_colunas_unicas_de_coluna_unica`, função pura que agrupa por
      `constraint_name` e só marca `unica=True` pra grupos de 1 coluna
- [x] `SobrescritaDeTabela._calcular_hash_estrutural` — `nao_nulavel`/
      `unica` entram na tupla hasheada por coluna, senão uma coluna que
      virasse NOT NULL/UNIQUE no banco não disparava aviso de mudança
      estrutural
- [x] `GeradorMarkdown`: coluna "Chave" renomeada pra "Restrição",
      `_marcadores_de_chave` virou `_marcadores_de_restricao` e passou a
      incluir `"UNIQUE"`/`"NOT NULL"` (suprimidos quando a coluna já é PK);
      `_linha_qualidade` mostra `"0.00% (garantido pelo schema)"` quando
      `nao_nulavel=True`, independente de `MetricasBaseColuna` já ter sido
      calculada; `_secoes_valores_frequentes` generaliza o aviso de baixo
      sinal (antes só PK) pra `unica=True`, com texto próprio, PK com
      precedência; seção "Valores frequentes por coluna" sempre renderiza o
      cabeçalho, com nota quando nenhuma coluna é elegível (achados
      testando o artefato real, ver seção própria abaixo)
- [x] Bugfix trivial embutido (achado em comentário da issue, sem PR
      separado): `CategoriaDeDado.JSON` faltava em
      `_CATEGORIAS_SEM_MINIMO_E_MAXIMO` — mesmo bug de comparação
      lexicográfica de Mínimo/Máximo já corrigido pras demais categorias
      textuais/estruturadas
- [x] `docs/low_level_design.md` e `plan/tasks.md` atualizados (modelos,
      queries dos dois Extratores, hash, comportamento do `GeradorMarkdown`)
- [x] `mypy --strict src` (47 arquivos, 0 erros) e `ruff check .` limpos

## Testes

- [x] `tests/unit/.../extractors/postgres/test_extrator_postgres.py` —
      3 testes existentes atualizados (assinatura de `_LinhaColuna` mudou)
      + asserções novas de `nao_nulavel`/`unica` no teste de estrutura
      completa
- [x] `tests/unit/.../extractors/mariadb/test_extrator_mariadb.py` —
      6 testes existentes atualizados + teste de borda novo
      (`test_unique_composta_nao_marca_nenhuma_coluna_como_unica`) cobrindo
      a lógica Python de agrupamento (testável sem banco real, ao contrário
      da colisão de nome, que exige JOIN SQL de verdade)
- [x] `tests/unit/.../overrides/test_sobrescrita_de_tabela.py` — teste de
      borda novo confirmando que o hash muda quando `nao_nulavel`/`unica`
      mudam
- [x] `tests/unit/.../generators/test_gerador_markdown.py` — 6 testes
      novos: NOT NULL garantido pelo schema (Qualidade dos dados **e**
      marcador na seção Colunas); marcador+aviso UNIQUE; PK+UNIQUE+NOT NULL
      não duplica nenhum dos três; FK+UNIQUE combina os dois marcadores;
      categoria JSON sem Mínimo/Máximo (espelha o teste já existente do
      UNKNOWN); seção "Valores frequentes por coluna" vazia explica o
      motivo em vez de desaparecer. Fixture `construir_coluna` (conftest)
      estendida com `chave_estrangeira`/`referencia`/`nao_nulavel`/`unica`
- [x] `tests/integration/extractors/postgres/` — schema `restricoes` novo
      (`contas`: UNIQUE nomeada + índice único solto; `enderecos`: UNIQUE
      composta) + 3 testes de borda novos
- [x] `tests/integration/extractors/mariadb/` — database `restricoes` novo
      reproduzindo a colisão de nome (`pedidos`/`clientes` com `UNIQUE KEY
      email` idêntica no mesmo database) + índice único solto + UNIQUE
      composta + 3 testes de borda novos
- [x] Verificação completa: `pytest tests/unit` (229 passed),
      `pytest tests/integration` (25 passed, via Docker real — 12 Postgres
      + 13 MariaDB), `mypy --strict`/`ruff` limpos
- [x] Verificação manual: `.md` gerado via script ad-hoc contra tabela com
      PK+UNIQUE, UNIQUE simples, FK+UNIQUE, NOT NULL e coluna comum
      combinados na mesma tabela — conferido visualmente que nenhum
      marcador/aviso duplica e o texto "garantido pelo schema" aparece só
      onde deveria

## Achados da banca de revisão (pós-desenho, validados empiricamente)

Diferente de revisão só sobre fixtures: o Engenheiro de Dados subiu
Postgres 16 e MariaDB 11 reais via testcontainers **antes** da
implementação, pra validar as duas perguntas técnicas do desenho — achou um
bug real e uma lacuna real, não hipotéticos.

> **Bug real: colisão de nome de constraint UNIQUE entre tabelas do mesmo
> schema no MariaDB.** Reproduzido com `pedidos.email UNIQUE` e
> `clientes.email UNIQUE` no mesmo database — a query sem
> `AND kcu.table_name = %s` retornava uma linha fantasma cruzando as duas
> tabelas, fazendo o agrupamento por `constraint_name` classificar `email`
> como membro de um grupo de 2 (logo `unica=False`), quando na verdade era
> uma UNIQUE single-column real em cada tabela. **Corrigido** antes de
> qualquer código de produção ser escrito (achado durante a fase de
> desenho, não numa revisão pós-implementação). **Validado a posteriori**:
> removi o filtro temporariamente, rodei só o teste de regressão
> (`test_extrair_tabela_com_constraint_de_mesmo_nome_em_outra_tabela_nao_confunde`)
> e confirmei que falha exatamente como o bug previa antes de restaurar o
> fix — prova de que o teste pega o bug, não é cobertura de fachada.

> **Lacuna real: índice único solto tem cobertura assimétrica entre
> motores.** `CREATE UNIQUE INDEX` sem `ADD CONSTRAINT` aparece em
> `information_schema.table_constraints` no MariaDB (mesma query já cobre),
> mas não aparece no Postgres de jeito nenhum — só constraints nomeadas.
> Sob o mesmo nome de campo (`unica`), isso seria uma inconsistência de
> comportamento entre as duas fontes suportadas. **Fechada** via captura
> Postgres por catálogo (`pg_index`) em vez de `information_schema`,
> cobrindo os dois casos (nomeada e solta) numa única query — decisão do
> usuário de fechar agora em vez de aceitar a assimetria.

> **`GeradorDbt` (issue #14) tem o mesmo viés estatístico, com consequência
> maior.** Não corrigido nesta issue (fora de escopo, decisão do usuário) —
> registrado via comentário na
> [issue #14](https://github.com/ThiagoLimaC/ddf/issues/14#issuecomment-5013843842)
> após o merge desta.

## Achados testando o artefato real (pós-implementação)

Diferente da banca formal (que revisou o desenho antes do código), estes
vieram do usuário rodando `scripts/prototipo_wizard_mariadb.py` contra um
banco real e inspecionando os `.md` gerados em `docs_gerados/` — mesmo
padrão de validação já usado na #13.

> **Coluna "Chave" não bastava — restrições viviam em dois lugares
> diferentes do artefato.** `nao_nulavel` só aparecia como texto dentro da
> célula de `percentual_nulo` (Qualidade dos dados); uma coluna NOT NULL
> sem ser PK/FK/UNIQUE ficava com a célula "Chave" em branco, escondendo a
> restrição de quem olha só a tabela de Colunas. **Corrigido:** coluna
> renomeada pra "Restrição", `_marcadores_de_chave` virou
> `_marcadores_de_restricao` e passou a incluir `NOT NULL` (suprimido
> quando a coluna já é PK, que implica os dois). O texto "garantido pelo
> schema" continua em Qualidade dos dados — não foi removido, só deixou de
> ser o único lugar onde a garantia aparece.

> **Seção "Valores frequentes por coluna" desaparecendo em silêncio quando
> nenhuma coluna é elegível.** Reproduzido com dado real: tabelas com
> amostra vazia (0 linhas extraídas) fazem toda coluna cair fora de
> `_secoes_valores_frequentes`, e a seção inteira sumia do `.md` sem
> explicação — parecia bug de geração, não fato sobre os dados. **Corrigido:**
> o cabeçalho "## Valores frequentes por coluna" agora é sempre renderizado;
> quando `secoes` está vazio, mostra uma nota explicando os motivos prováveis
> (amostra vazia ou métricas ainda não calculadas) em vez de omitir a seção.
> Mesma categoria de correção já aplicada na #13 pra coluna 100% nula
> (nota explícita em vez de omissão silenciosa).

## Pendências para próximas issues (não resolvidas aqui)

- **`GeradorDbt` (#14)** deve priorizar `nao_nulavel`/`unica` (garantia de
  schema) sobre a heurística amostral atual (`percentual_nulo`/
  `percentual_unico`) ao sugerir testes `not_null`/`unique` — comentário já
  registrado na #14, ver achado acima.
- **UNIQUE composto (2+ colunas) não é representado em lugar nenhum do
  domínio.** `unica=False` numa coluna que participa de uma UNIQUE composta
  não distingue "sem garantia nenhuma" de "única só em combinação com outra
  coluna" — aceito conscientemente (mesmo espírito do corte de escopo de
  CHECK/DEFAULT), mas documentado no docstring do campo pra não confundir
  consumidores futuros do artefato.
- **Tabelas particionadas duplicam captura de estrutura** entre tabela-mãe
  e cada partição no Postgres (`information_schema.tables` lista as duas
  como `BASE TABLE` independentes) — pré-existente, não introduzido por
  esta issue, mas fica mais visível agora que cada partição carrega seu
  próprio "NOT NULL garantido pelo schema" redundante. Comum em bancos de
  produção reais; vale uma issue própria se/quando aparecer como problema
  concreto.
- **CHECK/DEFAULT continuam fora de escopo**, por decisão de produto já
  fechada no corpo da issue original (sintaxe diverge entre motores, baixo
  valor de descoberta pra ferramenta de entendimento de dados).

# Issue #35 — feat: ExtratorMariaDB (segunda fonte relacional real)

## Decisões tomadas na discussão prévia (antes de implementar)

> **BOOLEAN inferido a partir da amostra real, não de convenção de nome ou
> largura de tipo.** Primeira proposta cogitada foi `tinyint(1)` → `BOOLEAN`
> (convenção de ORM). Descartada: MariaDB não guarda em lugar nenhum a
> distinção `BOOLEAN` vs `TINYINT(1)` — `BOOLEAN`/`BOOL` é só sinônimo léxico
> reescrito pelo parser no `CREATE TABLE`; nenhuma coluna de
> `information_schema` (incl. `COLUMN_TYPE`) preserva essa palavra depois que
> a tabela existe. Schemas reais usam `tinyint(1)` pra guardar inteiro
> pequeno de verdade (contador, flag multi-estado) — pra uma ferramenta de
> data dictionary, um falso positivo (chamar um inteiro de booleano no
> `schema.yml`/markdown gerado) é pior que um falso negativo. Segunda
> proposta (inferir por prefixo de nome de coluna, `is_`/`has_`) também
> descartada — seria especulação sobre nomenclatura, não sobre o tipo.
> **Decisão final:** `mapear_tipo_mariadb` continua função pura só de
> metadado (`tinyint` sempre → `INTEGER`, mesmo `tinyint(1)`);
> `ExtratorMariaDB` faz um passo de refinamento depois de montar a amostra —
> toda coluna cujo `COLUMN_TYPE` lido era `'tinyint(1)'` é promovida
> `INTEGER`→`BOOLEAN` só se todos os valores não-nulos amostrados estiverem
> em `{0, 1}`. Amostra vazia ou só nulos não promove (falta de evidência ≠
> evidência de booleano). Isso muda a ordem de construção em relação ao
> `ExtratorPostgres`: lá as colunas são finalizadas antes da amostra; aqui a
> finalização de colunas candidatas a `BOOLEAN` depende da amostra já
> carregada (`_promover_booleanos_pela_amostra`, chamada só depois do
> `SELECT` de amostra). Trade-off aceito conscientemente: como qualquer
> decisão baseada em amostra, é sensível ao `percentual` configurado (amostra
> pequena pode não conter o valor atípico que desmontaria a inferência) —
> mesma classe de incerteza que `PercentualDeLinhas` já assume em outros
> lugares do projeto.

> **ENUM e SET ganham categorias próprias — reabre escopo de
> `tipo_de_dado.py` (mesmo padrão da #9 pro FLOAT/CHAR/UUID/TIME).**
> Colapsar em `VARCHAR` (opção mais simples, cogitada primeiro) perderia
> informação real que um data dictionary quer mostrar: "esta coluna só
> aceita X/Y/Z". `ENUM` e `SET` são semanticamente diferentes — `ENUM` aceita
> exatamente 1 valor do conjunto, `SET` aceita 0..N valores combináveis
> (bitmask) — por isso categorias separadas
> (`CategoriaDeDado.ENUM`/`CategoriaDeDado.SET`), não uma `ENUM_LIKE`
> unificada: um `GeradorDbt` futuro geraria teste `accepted_values` pra
> `ENUM`, mas nada equivalente faz sentido pra `SET`. Ambas compartilham o
> atributo novo `TipoDeDado.valores_permitidos: tuple[str, ...] | None`
> (mesmo padrão de atributo compartilhado entre categorias já usado por
> `com_timezone` em `TIMESTAMP`/`TIME`). `information_schema.columns` não tem
> coluna separada com a lista de valores — vem embutida em `COLUMN_TYPE`
> (`"enum('a','b','c')"`, `"set('x','y')"`), então `mapear_tipo_mariadb`
> parseia essa string via regex (`_extrair_valores_enum`), desescapando
> aspas duplicadas (`''`) que representam uma aspa literal dentro de um
> valor — regra de quoting do MariaDB.

> **`dbutils` sem stub oficial — override mínimo de mypy, não stub local.**
> Diferente do `psycopg2` (resolvido na #9 com `types-psycopg2`, que existe
> no PyPI), não existe `types-dbutils`. Escrever um `.pyi` local só pra
> `PooledDB` (usada num único ponto do código) foi descartado por
> manutenção desproporcional ao ganho. Decisão: `[[tool.mypy.overrides]]`
> com `module = "dbutils.*"` e `ignore_missing_imports = true` em
> `pyproject.toml` — escopo mínimo, documentado aqui.

## Decisões fechadas durante a implementação

> **Construtor sem DSN único, e sem `database` fixo.** Diferente do Postgres
> (uma string DSN + schema opcional na própria conexão), `pymysql.connect()`/
> `PooledDB` usam parâmetros discretos. O `Extrator` Port não força
> assinatura de construtor (só as 3 methods), então
> `ExtratorMariaDB.__init__(self, host, user, password, configuracao,
> port=3306, max_conexoes=8)` é a assinatura adotada — **sem** parâmetro
> `database`. Diferente do Postgres, que sempre conecta a um database fixo e
> navega schemas dentro dele, `ExtratorMariaDB` representa uma conexão ao
> *servidor* MariaDB, não a um database específico — cada escopo (=database)
> é endereçado explicitamente por chamada (`listar_tabelas(escopo)`,
> `extrair_tabela(escopo, tabela)`), com `listar_escopos()` descobrindo quais
> existem. Essa ausência de "database default" é o próprio reflexo, no
> construtor, do colapso schema/database que esta issue existe pra provar.

> **Sem semáforo manual, ao contrário do Postgres.**
> `ThreadedConnectionPool` do psycopg2 levanta `PoolError` quando esgotado —
> por isso o semáforo manual na #9. `PooledDB` aceita `blocking=True`
> nativamente, que já bloqueia a chamada até liberar conexão em vez de
> levantar erro — reimplementar isso com `threading.Semaphore` seria
> redundante. Liberação de conexão via `conexao.close()` (DBUtils devolve a
> conexão ao pool, não fecha de fato a conexão física).

> **Identificadores via helper de escaping próprio, sem dependência
> equivalente ao `psycopg2.sql`.** `pymysql` não tem um equivalente ao
> `psycopg2.sql.Identifier`. A query de amostra usa um helper local
> (`_quotar_identificador`, escapando crase duplicada) pra schema/tabela, e
> `%s` parametrizado pro percentual — mesmo espírito de segurança do
> Postgres, sem a dependência.

> **PK e FK num único ponto de leitura — mais simples que o Postgres.**
> `information_schema.key_column_usage` do MariaDB já traz
> `REFERENCED_TABLE_SCHEMA`/`REFERENCED_TABLE_NAME`/`REFERENCED_COLUMN_NAME`
> direto nas mesmas linhas que descrevem colunas de chave — PK identificada
> por `constraint_name = 'PRIMARY'`, FK por `referenced_table_name IS NOT
> NULL`. O Postgres precisa de dois `JOIN`s adicionais
> (`table_constraints` + `constraint_column_usage`) porque seu
> `information_schema.key_column_usage` não inclui a coluna referenciada.
> Diferença real de dialeto, não escolha de implementação.

> **`total_linhas` via `information_schema.tables.TABLE_ROWS`, com
> `NULL`-check que o Postgres não precisa.** Paralelo ao `reltuples` do
> Postgres (estimativa, não `SELECT COUNT(*)`), mas `TABLE_ROWS` pode ser
> `NULL` (não só um número "não confiável" como `reltuples=-1`) logo após a
> criação de uma tabela, antes de qualquer `ANALYZE`. `extrair_tabela` trata
> `None` e resultado ausente da mesma forma: `total_linhas = 0`.
>
> **Margem de erro maior que a do Postgres, aceita conscientemente.** A
> documentação oficial do MySQL/MariaDB registra `TABLE_ROWS` do InnoDB como
> uma estimativa que pode divergir em até ~40–50% do valor real (amostragem
> de páginas via estatística persistente, não contagem real) — pior que a
> margem tipicamente observada em `reltuples` do Postgres. Não existe
> alternativa mais precisa e igualmente barata: `SELECT COUNT(*)` é exato mas
> exige full scan (o mesmo custo que a decisão original da #9 rejeitou);
> `ANALYZE TABLE` antes de ler `TABLE_ROWS` atualiza a estatística mas
> continua sendo estimativa, e adiciona uma operação a mais numa extração que
> deveria ser só leitura. Decisão: manter `TABLE_ROWS` como está — mesma
> categoria de trade-off já aceita pro Postgres, só com margem maior,
> documentada aqui pra quem for interpretar `total_linhas` do MariaDB com
> mais cautela que o do Postgres.

> **Amostragem via `WHERE RAND() <= percentual/100`, sem `ORDER BY`.**
> MariaDB não tem `TABLESAMPLE`. `ORDER BY RAND() LIMIT n` foi descartado
> (mesmo raciocínio da #9 sobre `LIMIT` sem amostragem real): exigiria sort
> completo da tabela. `RAND() <= p` é O(n) sem sort, mesmo custo de uma
> varredura completa com um predicado — aceitável pelo mesmo motivo que a
> abordagem do Postgres foi aceita: não há forma de amostrar sem tocar o
> dialeto da fonte.

> **Mapeamento de tipos refinado contra `testcontainers` real
> (`mariadb:11`).** Conjunto coberto: `varchar`, `char`, `tinytext`/`text`/
> `mediumtext`/`longtext`, `decimal`, `tinyint`/`smallint`/`mediumint`/`int`,
> `bigint`, `float`/`double`, `datetime`/`timestamp`, `date`, `time`, `json`
> (alias de `longtext` no MariaDB, mapeado pra `CategoriaDeDado.JSON` mesmo
> assim — preserva a intenção do schema), `uuid` (nativo desde MariaDB
> 10.7+), `enum`/`set`. Não cobre variantes `UNSIGNED`, `blob`/`binary`,
> `bit`, `year`, tipos geométricos — caem em `UNKNOWN`, mesmo nível de
> "conjunto representativo" que a #9 entregou pro Postgres, não escopo
> especulado.

> **`--import-mode=importlib` no pytest — necessário assim que a 2ª fonte
> apareceu.** `tests/unit/.../extractors/postgres/test_mapeamento_de_tipos.py`
> e `.../mariadb/test_mapeamento_de_tipos.py` têm o mesmo nome de arquivo, e
> nenhum diretório de teste do projeto tem `__init__.py` (convenção
> deliberada desde a #9). No modo `prepend` (default do pytest), isso causa
> `import file mismatch` na coleta. Alternativa descartada: adicionar
> `__init__.py` em toda a árvore de `tests/` — mudança maior, e
> `--import-mode=importlib` é a solução recomendada pelo próprio pytest pra
> exatamente esse caso (múltiplas fontes/adapters com nomes de arquivo
> espelhados), sem exigir pacotes formais em testes.

## Escopo desta issue

- [x] `pyproject.toml` — `pymysql`, `dbutils` nas dependências;
      `testcontainers[mysql]`, `types-pymysql` no grupo dev; override de
      mypy pra `dbutils.*`; `--import-mode=importlib` nos `ini_options`
- [x] `domain/model/common/tipo_de_dado.py` — `CategoriaDeDado.ENUM`/`SET`,
      atributo `valores_permitidos`, `_ATRIBUTOS_PERMITIDOS` atualizado
- [x] `infrastructure/adapters/extractors/mariadb/mapeamento_de_tipos.py` —
      `mapear_tipo_mariadb()`, função pura, testada isoladamente
- [x] `infrastructure/adapters/extractors/mariadb/extrator_mariadb.py` —
      `ExtratorMariaDB(Extrator)`: pool preguiçoso via `PooledDB`,
      `listar_escopos`/`listar_tabelas`/`extrair_tabela` completos,
      refinamento de BOOLEAN pela amostra
- [x] Reutiliza `PercentualDeLinhas` sem nenhuma mudança
- [x] Testes unit (pool/cursor fake, feliz/erro/borda) + integração via
      `testcontainers` (`mariadb:11` real)
- [x] Teste explícito de Open/Closed: `isinstance(ExtratorMariaDB(...),
      Extrator)`, suíte completa de Postgres passa sem alteração nenhuma
- [x] `mypy --strict src` (42 arquivos, 0 erros) e `ruff check .` limpos

## Testes

- [x] `tests/unit/.../extractors/mariadb/test_mapeamento_de_tipos.py` —
      feliz por categoria (incl. `tinyint` sempre INTEGER nesta função,
      `enum`/`set` com `valores_permitidos`), borda (tipo desconhecido →
      `UNKNOWN`, valor de enum com aspa escapada)
- [x] `tests/unit/.../extractors/mariadb/test_extrator_mariadb.py` —
      conformidade ao Port, construção preguiçosa, `listar_escopos`/
      `listar_tabelas` (feliz/borda), `extrair_tabela` (feliz completo, erro
      escopo/tabela inexistente, erro conexão recusada, borda
      `TABLE_ROWS=NULL`), refinamento de BOOLEAN (feliz: promove; borda:
      valor atípico não promove, amostra vazia não promove)
- [x] `tests/integration/extractors/mariadb/` via `testcontainers`
      (`mariadb:11` real, 4 databases semeados — `vendas`/`pessoa`/`rh`/
      `vazio`): `listar_escopos`/`listar_tabelas`, `extrair_tabela` completo
      (incl. `DATETIME`, `ENUM` com valores reais, `tinyint(1)` promovido a
      `BOOLEAN` com dados reais 0/1), erro tabela inexistente, erro conexão
      recusada, borda FK cross-database (`rh.funcionario` → `pessoa.pessoa`)
- [x] Verificação completa: `pytest tests/unit` (172 passed),
      `pytest tests/` (190 passed, incl. 18 de integração via Docker real —
      8 Postgres + 10 MariaDB), suíte de Postgres sem nenhuma alteração

## Conclusão sobre a dúvida da #34

`nome_escopo: str` (flat) se provou suficiente para o colapso schema/database
do MariaDB — `ExtratorMariaDB` implementa o `Extrator` Port sem tocar em
Extraction/Curation/Analysis, nas outras Ports, no `OrquestradorParalelo` ou
na `SobrescritaDeTabela` (única mudança fora do adapter foi a reabertura
pontual de `tipo_de_dado.py` pra `ENUM`/`SET`, que é sobre tipo de coluna, não
sobre modelagem de escopo). `listar_escopos()` devolve os databases do
MariaDB do mesmo jeito que devolveria schemas do Postgres — a Port não
precisou saber a diferença.

**Mas, como já registrado na ressalva da banca de revisão da #34, isso
confirma só a hipótese flat, não a hierárquica.** Postgres e MariaDB são
ambos flat (um único nível abaixo do "database"/"schema" endereçável por uma
`str`) — só de naturezas diferentes (schema aninhado num database vs.
schema=database). Um caso genuinamente hierárquico de três níveis (ex.:
SQL Server, `outro_database.schema.tabela` endereçando bancos diferentes na
mesma conexão) continua sem validação real. **Não generalizar o resultado
desta issue além do que ela prova**: `nome_escopo: str` está confirmado para
fontes relacionais flat; a pergunta sobre hierarquia de 3+ níveis permanece
aberta pra quando (e se) uma fonte desse tipo entrar no roadmap.

## Achados da banca de revisão (Arquiteto de Software + PO + Engenheiro de
Dados) e correções aplicadas

Banca rodada em paralelo sobre o diff completo desta issue. Veredito unânime:
**Aprovado**, nenhum bloqueante. Achados "nice-to-have" incorporados:

> **`tinyint(1) unsigned` não era candidato à promoção de BOOLEAN —
> corrigido.** O Engenheiro de Dados testou empiricamente contra
> `mariadb:11` real e confirmou: `COLUMN_TYPE` de um `TINYINT(1) UNSIGNED`
> vem `"tinyint(1) unsigned"`, que não batia com a igualdade exata
> `column_type == "tinyint(1)"` usada pra marcar candidatos. Corrigido pra
> `column_type.startswith("tinyint(1)")` — cobre a variante `unsigned` sem
> risco de falso positivo com outras larguras (`"tinyint(10)"` não começa
> com `"tinyint(1)"` porque o 10º caractere diverge: `)` esperado vs `0`
> real). Teste novo:
> `test_tinyint_um_unsigned_tambem_e_candidato_a_boolean`.

> **Margem de erro de `TABLE_ROWS` documentada.** O Engenheiro de Dados
> confirmou (documentação oficial MySQL/MariaDB) que `TABLE_ROWS` do InnoDB
> pode divergir em até ~40–50% do valor real — pior que a margem típica de
> `reltuples` no Postgres. Não há alternativa mais precisa e igualmente
> barata (`COUNT(*)` é exato mas exige full scan, `ANALYZE TABLE` continua
> sendo estimativa e adiciona uma operação a mais numa extração que deveria
> ser só leitura). Decisão: manter como está, documentar a margem maior (ver
> nota acima, já incorporada ao texto de `total_linhas`).

> **FK duplicada na mesma coluna — sobrescrita silenciosa virou Aviso não-
> fatal, corrigido em `ExtratorMariaDB` E retroativamente em
> `ExtratorPostgres`.** O Engenheiro de Dados apontou que uma coluna com 2+
> constraints FK (modelagem polimórfica rara, mas válida no motor) fazia
> `colunas_fk[nome_coluna_fk] = ...` sobrescrever a referência anterior em
> silêncio — e o mesmo padrão já existia no `ExtratorPostgres` desde a #9,
> não era uma lacuna nova do MariaDB. Como `ColunaExtraida.referencia` é
> singular por design (não uma lista — nenhuma issue até agora motivou essa
> estrutura), a correção não mexeu no modelo de domínio: extraída a lógica
> de construção pra um helper agnóstico de fonte,
> `infrastructure/adapters/extractors/construir_colunas_fk.py`
> (`construir_colunas_fk`), reaproveitado por `ExtratorMariaDB` e
> `ExtratorPostgres`. Ao detectar colisão, emite um `Aviso` (mecanismo já
> existente em `domain/shared/aviso.py`, usado aqui pela primeira vez por um
> Extrator) nomeando qual referência foi descartada, em vez de simplesmente
> sobrescrever. `Sucesso(TabelaExtraida(...), avisos=avisos)` em ambos os
> adapters. Testes novos:
> `tests/unit/infrastructure/adapters/extractors/test_construir_colunas_fk.py`
> (helper isolado) + um teste de borda em cada
> `test_extrator_mariadb.py`/`test_extrator_postgres.py` confirmando que o
> `Aviso` aparece em `resultado.avisos` no nível do Extrator completo.
> **Nota:** essa correção toca `ExtratorPostgres`, o que a rigor quebra a
> alegação anterior de "zero mudança fora do adapter MariaDB" — mas é uma
> mudança deliberada, pedida explicitamente após a correção ter sido
> identificada como compartilhada entre os dois adapters, não uma violação
> acidental do critério de Open/Closed (que é sobre o *Extraction Context/
> Ports/Orquestrador* não precisarem mudar pra MariaDB plugar, não sobre
> nunca mais tocar em `ExtratorPostgres` por qualquer motivo).

## Pendências para próximas issues (não resolvidas aqui)

- Variantes `UNSIGNED` fora de `tinyint(1)` (ex. `int unsigned`), `blob`/
  `binary`, `bit`, `year`, tipos geométricos do MariaDB caem em `UNKNOWN` —
  refinar se/quando um schema real exigir.
- `GeradorDbt` (issue futura) é o consumidor real de `valores_permitidos`
  (`ENUM`/`SET`, teste `accepted_values`) e da distinção rica de tipos em
  geral — não implementado aqui, só o modelo que a suporta.
- Estrutura hierárquica de escopo (SQL Server-like) — ver conclusão acima;
  permanece em aberto, não é dívida desta issue.

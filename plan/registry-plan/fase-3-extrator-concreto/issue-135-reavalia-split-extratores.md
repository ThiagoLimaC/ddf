# Issue #135 — reavalia split de extrator_postgres.py/extrator_mariadb.py

## Contexto

A issue #135 pede reavaliação de split dos dois Extratores concretos, que
cresceram de novo desde a última avaliação (#106): a issue foi aberta citando
502/571 linhas, mas a contagem real no início desta rodada era **793 linhas**
(Postgres) e **857 linhas** (MariaDB) — o crescimento veio do commit
`b1b7a44` (issue #126, "paraleliza leitura intra-tabela via connectorx"),
posterior à abertura da #135.

A #106 já havia avaliado os dois Extratores e rejeitado split de pool/cache
por risco de import circular e de espalhar conhecimento de lock privado por
múltiplos arquivos — só aprovou extrair funções puras de construção de
coluna (`_construcao.py`). A hipótese desta rodada era que "leitura paralela
intra-tabela via connectorx" (o código novo desde a #106) fosse um eixo de
responsabilidade genuinamente novo, não avaliado antes, e candidato a módulo
próprio (`_paralelo.py`).

## 1ª rodada — banca completa (arquiteto-de-software + engenheiro-de-dados + po-revisor)

Cada um leu os dois Extratores por completo mais os registry-plans das
#80/#106/#126, em paralelo.

**Veredito: rejeitar o split de subpacote, unânime nos três pareceres.** O
eixo de leitura paralela colapsa na mesma razão de mudança que a #106 já
usou para rejeitar o split de pool/cache:

- Os métodos com estado (`_ler_tabela_em_paralelo`, `_dominio_de_pk` no
  MariaDB, `_total_blocos` no Postgres) dependem de
  `self._conexao`/`self._conexao_ja_reservada`/`self._semaforo` — movê-los
  pra fora da classe exige ou passar a instância inteira como parâmetro
  (padrão já rejeitado explicitamente na #106: import circular sem
  precedente, espalha conhecimento de atributos privados de lock por 3
  arquivos sem contrato de tipo), ou passar semáforo/locks individualmente,
  mesmo problema.
- Lock-ordering sensível com precedente concreto de bug: `_dominio_de_pk`
  (MariaDB) já teve que ser movido pra antes de `reservar_conexoes()` na
  #126 pra evitar self-deadlock. Espalhar esse invariante por um módulo
  separado transforma um contrato hoje visível dentro de uma classe coesa
  numa convenção implícita entre arquivos.
- Zero reuso real: cada método candidato tem exatamente 1 call site, dentro
  da própria classe.
- Divergência de garantia entre motores (engenheiro de dados): Postgres usa
  snapshot exportado, MariaDB não tem equivalente e aceita risco via
  `Aviso` — não é diferença de detalhe, é diferença de garantia de
  correção. A fatia genuinamente motor-agnóstica (`deve_paralelizar_leitura`,
  `reservar_conexoes`, `liberar_conexoes`) já foi extraída corretamente na
  #126, em `extractors/comum/leitura_paralela_intra_tabela.py`.

**Decisão: não fazer split de subpacote.** Tamanho de arquivo grande aqui é
sintoma de complexidade genuína de coordenação de concorrência (pool/
semáforo/snapshot), não de responsabilidade misturada — mesmo veredito da
#80/#106, reaplicado ao código novo.

**Único gesto de reorganização aprovado nesta rodada**: `_query_particao_ctid`
(Postgres) não referencia `self` — função pura disfarçada de método,
mesmo padrão de `particoes_de_blocos` em `_construcao.py`.

**Achado à parte (fora do escopo textual original, incluído por decisão do
usuário)**: o engenheiro de dados encontrou um self-deadlock potencial em
`ExtratorPostgres._total_blocos` — chamado depois de `reservar_conexoes()`
via `self._conexao()` (acquire bloqueante do semáforo já esgotado), quando
`max_conexoes_por_tabela == max_conexoes` (configuração explicitamente
permitida pelo construtor). Mesma classe de bug já corrigida no MariaDB pela
#126 (`_dominio_de_pk` movido pra antes da reserva), não espelhada pro
Postgres.

## 2ª rodada — objeto de conexão composto (pedido do usuário)

O usuário perguntou de novo com outro ângulo: puramente por navegabilidade/
manutenção (não é sobre SRP forçado), dá pra organizar os Extratores em mais
arquivos? Banca reavaliou uma ideia levantada pelo próprio arquiteto na 1ª
rodada: extrair pool + semáforo + locks para um **objeto composto** (não
uma função solta recebendo a instância inteira — o que a #106 já rejeitou).

**Veredito: aprovado por unanimidade, design genuinamente diferente do
rejeitado na #106.** Resolve os dois motivos concretos da rejeição
anterior:

- **Sem ciclo de import**: `_GerenciadorDeConexoesPostgres`/
  `_GerenciadorDeConexoesMariaDB` são classes-folha que não importam o tipo
  do Extrator de volta — dependência estritamente unidirecional.
- **Sem lock cru espalhado**: `_semaforo`/`_lock_pool`/
  `_lock_reserva_paralelismo` ficam privados dentro do objeto; o Extrator
  só chama API pública (`conexao()`, `conexao_ja_reservada()`, `reservar()`,
  `liberar()`).

**Assimetria real preservada, sem forçar simetria artificial**: Postgres
precisa de `conexao_ja_reservada()` (conexão líder do snapshot); MariaDB
não tem equivalente (connectorx abre conexão própria via DSN, nunca toma
emprestado do `PooledDB`). Duas classes concretas separadas por dialeto,
sem Protocol/base compartilhada — isso nunca cruza um Port real.

**O que fica fora do objeto**: `_cache_schemas`/`_lock_cache_schemas`/
`_obter_metadados_schema` (cache de catálogo é eixo diferente de conexão) e
toda lógica de dialeto/extração (`_dominio_de_pk`, `_ler_tabela_em_paralelo`,
`_total_blocos`, `_largura_media_real`, `_query_particao_ctid`) — esses só
trocam `self._conexao(...)` por `self._conexoes.conexao(...)`.

**Ressalva do engenheiro de dados, incorporada ao design**: a composição
melhora auditabilidade geral, mas não previne por si só a classe de bug do
self-deadlock — o risco vive na fronteira entre o objeto e quem o chama.
Reforço adotado: `reservar()` devolve `TokenDeReserva | None`, e
`conexao_ja_reservada()` passa a **exigir esse token como argumento** — a
violação (chamar sem ter reservado) vira erro de tipo, não lapso de leitura
de docstring.

Impacto de linhas estimado nesta rodada: Postgres 793 → ~700, MariaDB 857 →
~800 — vendido como navegabilidade/testabilidade, não como correção de SRP.

## 3ª rodada — pesquisa de padrões reais (Clean Code + projetos de produção)

O usuário achou o ganho da 2ª rodada insuficiente e pediu pesquisa real na
internet (não raciocínio de memória) por padrões de segmentação de classe
grande, incluindo Clean Code/Clean Architecture (Robert C. Martin) e
exemplos de projetos Python de produção.

**Clean Code (Cap. 10), aplicado com rigor**: o critério real de Martin pra
dividir uma classe não é contagem de linha (heurística solta do Cap. 5, que
nem o próprio autor segue à risca) — é **coesão**: dividir quando um
subconjunto de métodos usa só um subconjunto das variáveis de instância. Nos
dois Extratores, praticamente todo método toca o mesmo conjunto de estado —
o caso que o próprio Cap. 10 descreve como "não dividir".

**Projetos Python de produção reais** (verificado via WebFetch direto no
código-fonte): `SQLAlchemy.Connection` e `pandas.NDFrame` (**12.865 linhas
numa única classe**) mantêm núcleo coeso grande sem fatiamento mecânico por
LOC — delegam a objetos colaboradores (padrão que a 2ª rodada já aplicou).
Onde projetos reais fatiam (`httpx.Client`/`psycopg3`, sync vs. async) é por
eixo comportamental real, que não existe nos Extratores do ddf.

**Padrão de mixin espalhado por arquivo — testado e rejeitado**: sob
`mypy --strict`, cada método de mixin que toca estado da classe final
precisa de `self: Protocolo` explícito (doc oficial do mypy), que na
prática vira quase-espelho de todo o estado da classe — e ainda assim não
garante ordem de aquisição de lock. Reabre o risco já rejeitado, "validado"
por tipagem que não previne o bug real de concorrência.

**Proposta aceita**: estender o padrão que o projeto já usa (função pura em
`_construcao.py`) para mais dois blocos que são lógica pura disfarçada de
método:

1. Transformação de `_obter_metadados_schema` (agrupamento de linhas cruas
   de cursor via `defaultdict`) — vira `montar_metadados_do_schema(...)` em
   `_construcao.py`. Ganho estimado: ~70-75 linhas por Extrator.
2. Construção de `consulta_amostra` dentro do `match requisicao` de
   `extrair_tabela` (Postgres) — vira `montar_consulta_amostra(...)` em
   `_construcao.py`. Ganho estimado: ~30-35 linhas.

Resultado final estimado: **Postgres 793 → ~570-580 linhas, MariaDB 857 →
~570-600 linhas** (redução total de ~27%, contra ~12% só com a composição
de conexão).

**O que fica de fora, e por quê**: `_obter_pool`/`conexao`/
`conexao_ja_reservada`/`_ler_tabela_em_paralelo`/orquestração de
`extrair_tabela` continuam na classe — estatefuis por natureza. Mesmo
núcleo que SQLAlchemy mantém monolítico na `Connection`. Reduzir mais que
isso exigiria reabrir os riscos já rejeitados ou cortar comportamento real
— fora do escopo desta issue.

## Escopo

- [x] `extractors/postgres/_conexoes.py` (novo) — `_GerenciadorDeConexoesPostgres`:
      pool, semáforo, locks, `conexao()`/`conexao_ja_reservada(token)`/
      `reservar()`/`liberar(token)`, `TokenDeReserva`
- [x] `extractors/mariadb/_conexoes.py` (novo) — `_GerenciadorDeConexoesMariaDB`:
      mesmo formato, sem `conexao_ja_reservada` (sem caso de uso)
- [x] `ExtratorPostgres`/`ExtratorMariaDB` passam a compor
      `self._conexoes`; todos os call sites de pool/semáforo migrados —
      `_max_conexoes`/`_connect_timeout`/`_pool`/`_semaforo`/`_lock_pool`/
      `_lock_reserva_paralelismo` saem do Extrator; `_host`/`_user`/
      `_password`/`_port` continuam duplicados no `ExtratorMariaDB` (config
      de dialeto pra montar DSN do connectorx, fora do escopo de conexão)
- [x] Teste novo `test_conexoes.py` por dialeto (semáforo, pool sob
      concorrência, release garantido) — sem tocar nos testes de
      concorrência existentes do Extrator inteiro. 604→623 testes unit
      (+19), 61 testes de integração (testcontainers) passam sem alteração
      de asserção nos dois dialetos
- [x] `postgres/_construcao.py`/`mariadb/_construcao.py` ganham
      `montar_metadados_do_schema(...)` — `_obter_metadados_schema` na
      classe principal fica só com a orquestração (conexão + lock de cache)
- [x] `postgres/_construcao.py` ganha `montar_consulta_amostra(...)` —
      MariaDB mantém o próprio `match` (parâmetros `%s` do driver, forma
      diferente o bastante pra não generalizar artificialmente)
- [x] Teste unitário novo para as duas funções puras acima, com dado
      sintético (sem conexão real) — 10 testes novos entre os dois dialetos
- [x] `_query_particao_ctid` (Postgres) movida para `postgres/_construcao.py`
      como `query_particao_ctid`, função pura sem `self`. Sem equivalente no
      MariaDB (`_dominio_de_pk`/construção de queries usam config de
      instância)
- [x] Fix do self-deadlock: `extrair_tabela` (Postgres) calcula
      `total_blocos` **antes** de `self._conexoes.reservar()`, mesmo formato
      do bloco `pk_elegivel`/`dominio_pk` já existente no MariaDB (sonda
      falha → `elegivel_paralelo = False`, cai pro sequencial em silêncio,
      mesmo tratamento que o MariaDB já dá pra `_dominio_de_pk` falho);
      `_ler_tabela_em_paralelo` passa a receber `total_blocos: int` como
      parâmetro em vez de calcular internamente (também removeu os
      parâmetros `total_linhas`/`largura_media_bytes`, mortos — nunca lidos
      dentro do método, achado durante a refatoração)
- [x] Teste de integração novo
      (`test_max_conexoes_por_tabela_igual_a_max_conexoes_nao_trava`) que
      reproduz `max_conexoes == max_conexoes_por_tabela` contra Postgres
      real (testcontainers), rodando a extração numa thread com timeout —
      prova que completa em vez de travar
- [x] `mypy --strict src` (97 arquivos) + `ruff check .` + `pytest
      tests/unit` (633 testes) + `pytest tests/integration/extractors/
      {postgres,mariadb}` (62 testes) limpos após cada etapa, zero mudança
      de asserção nos testes pré-existentes
- [x] Re-medido `wc -l` dos dois Extratores ao final: **Postgres 793 → 588
      linhas** (levemente acima da meta ~570-580, diferença sem
      significado — a régua de linha nunca foi o critério real de sucesso,
      só uma heurística; ver rodada 3), **MariaDB 857 → 725 linhas**
      (redução menor que a meta ~570-600 estimada — a extração de
      `montar_consulta_amostra` era só do Postgres, o MariaDB só recebeu a
      composição de conexão + `montar_metadados_do_schema`)

## Fechamento

Decisão final registrada: **não fazer split de subpacote** (rejeitado nas
3 rodadas). Reorganização aplicada: objeto de conexão composto por dialeto
(`_conexoes.py`) + extração de 3 blocos de lógica pura pra `_construcao.py`
(`montar_metadados_do_schema` × 2, `montar_consulta_amostra`,
`query_particao_ctid`) + correção de um bug de self-deadlock encontrado
durante a revisão (fora do escopo textual original, incluído por decisão
do usuário). Zero mudança de comportamento observável, exceto a correção
do deadlock em si (que só se manifestava num caso-limite de configuração
nunca coberto por teste antes desta issue).

## Fora de escopo (avaliado e descartado)

- Split de `_ler_tabela_em_paralelo`/`_dominio_de_pk`/`_total_blocos` em
  módulo separado (função solta recebendo a instância, ou mixin com
  `self: Protocol`) — rejeitado nas 3 rodadas, mesmo risco de import
  circular/lock-ordering identificado na #106.
- Calibração de `MINIMO_CONEXOES_PARALELISMO=2` (achado secundário do
  engenheiro de dados: o caso-limite de 1 única partição via `connectorx` é
  mais lento que o caminho sequencial, segundo o spike da #126) — não é
  regressão de correção, só de performance no caso-limite. Candidato de
  calibração futura, não implementado aqui.

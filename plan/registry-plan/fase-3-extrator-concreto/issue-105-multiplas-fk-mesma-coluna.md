# Issue #105 — modela múltiplas FK numa mesma coluna, hoje descartada com Aviso

Plano completo revisado em `/home/dev/.claude/plans/sorted-crunching-sutherland.md`
(sessão de planejamento). Banca de revisão completa (arquiteto-de-software +
engenheiro-de-dados + po-revisor) rodada sobre o plano antes da
implementação — exigência explícita da própria issue por ser mudança
estrutural cross-context, mesmo critério de #44/#89/#95. Todos aprovaram
com ressalvas; achados incorporados abaixo antes do código.

## Contexto

`construir_colunas_fk` (compartilhado por `ExtratorPostgres` e
`ExtratorMariaDB`) resolvia a FK de uma coluna com "last wins": quando uma
coluna tem 2+ constraints FK distintas de coluna única apontando para
tabelas diferentes (modelagem polimórfica sem discriminator), só a última
lida sobrevivia — as demais eram descartadas silenciosamente (só um
`Aviso` não-fatal nomeava a perda). Evidência real, não sintética: rodando
o wizard contra um MariaDB gerenciado com 843 tabelas, 3 colunas em
produção têm esse padrão (`member_no`, `ps_partkey`, `ps_suppkey`),
achado durante o teste pós-implementação da #104.

Diferença de FK composta (`RestricaoDeFkComposta`, issue #95): lá é 1
constraint com 2+ colunas; aqui são 2+ constraints distintas de coluna
única na mesma coluna. Os dois mecanismos convivem sem conflito — já
usam as mesmas linhas cruas de `fks_por_tabela` (5-tupla com
`constraint_name`); só o agrupamento por constraint (FK composta) usava
esse campo, o agrupamento por coluna o ignorava e sobrescrevia.

## Decisões fechadas com a banca

- **Modelagem:** `ColunaExtraida.referencia: ReferenciaDeColuna | None`
  vira `referencias: list[ReferenciaDeColuna]` (default `[]`) —
  substitui o campo singular, não duplica (alternativa "campo novo ao
  lado do singular" descartada: duplicaria o conceito permanentemente).
  `chave_estrangeira` continua bool, agora `bool(referencias)`. Ordem da
  lista é determinística, herdada da ordem das queries de catálogo (ambas
  já ordenam por `constraint_name`), sem trabalho extra de ordenação.
- **Validator estrutural (achado do arquiteto-de-software):** os três
  modelos (`ColunaExtraida`, `ColunaCurada`, `ColunaAnalisada`) têm um
  `model_validator` idêntico (`_valida_referencia_de_chave_estrangeira`)
  que precisava ser atualizado de `self.referencia is None`/`is not None`
  para `bool(self.referencias)` — é o único invariante estrutural do
  campo; esquecê-lo deixaria `chave_estrangeira=True` com `referencias=[]`
  passar sem erro.
- **dbt — achado bloqueante do engenheiro-de-dados:** emitir um teste
  `relationships` por referência quando a coluna tem 2+ FKs é
  semanticamente errado. O teste valida "todo valor não-nulo existe na
  tabela pai"; para uma coluna que referencia A OU B (FK polimórfica sem
  discriminator), qualquer linha que aponte pra B falha o teste contra A
  (a menos que os espaços de PK nunca colidam, o que não é garantido) —
  seria falso positivo garantido na maioria dos casos reais, não
  cobertura extra. Precedente de mercado (dbt/DataHub/OpenMetadata): FK
  ambígua é documentada, não testada automaticamente; quando um
  engenheiro tem FK ambígua real, escreve `relationships` manual com
  `where` filtrando pelo discriminator.
  **Decisão:** `GeradorDbt` só emite `relationships` quando a coluna tem
  exatamente 1 referência (comportamento atual preservado). Quando tem
  2+, nenhum teste automático é emitido — em vez disso, um `Aviso`
  explica a ambiguidade. `GeradorMarkdown`/`GeradorContextoDeIA`
  continuam listando **todas** as referências normalmente — ali é
  documentação, sem risco de falso positivo.
- **Queries de catálogo (achado do engenheiro-de-dados):** nenhuma
  mudança de SQL necessária. Postgres (`pg_constraint`, filtro
  `contype='f'`) e MariaDB (`key_column_usage`, sem JOIN com
  `table_constraints`) já retornam uma linha por constraint mesmo com 2+
  constraints na mesma coluna, confirmado por leitura de catálogo — não
  há JOIN que colapse ou duplique errado.
- **`GeradorContextoDeIA`:** `"referencias"` sempre presente no JSON por
  coluna (lista vazia quando não há FK) — consistência com os demais
  campos de **coluna** (`chave_primaria`, `chave_estrangeira`, etc., que
  nunca são omitidos), diferente do padrão de omissão usado pelos campos
  de **tabela** (`restricoes_unicas`/`restricoes_fk_compostas`).
- **Comentários desatualizados corrigidos (achado do arquiteto):**
  `domain/model/common/restricao_de_fk_composta.py` e
  `extractors/comum/construir_restricoes_fk_compostas.py` citavam
  `ColunaExtraida.referencia` singular como contraste com FK composta.

## 1. Domínio (Extraction → Curation → Analysis)

- [x] `ColunaExtraida`/`ColunaCurada`/`ColunaAnalisada`: `referencia` →
      `referencias: list[ReferenciaDeColuna] = Field(default_factory=list)`
      (propagação automática via `model_dump`/`model_validate` já
      existente, só a declaração muda nos 3 modelos)
- [x] `_valida_referencia_de_chave_estrangeira` atualizado nos 3 modelos
      para `bool(self.referencias) == self.chave_estrangeira`
- [x] Docstrings de `restricoes_fk_compostas` corrigidas nos 3 modelos
      (citavam `.referencia` singular)

## 2. Helper agnóstico de fonte + Extratores concretos

- [x] `extractors/comum/construir_colunas_fk.py` — reescrito: assinatura
      `construir_colunas_fk(linhas_fk) -> dict[str, list[ReferenciaDeColuna]]`,
      sem `Aviso`/`origem` (nada mais é descartado). Agrupa por coluna
      preservando ordem de chegada. Docstring reescrita
- [x] `extractors/postgres/_construcao.py` / `extractors/mariadb/_construcao.py`
      — `_construir_coluna`: `colunas_fk: dict[str, list[ReferenciaDeColuna]]`,
      `referencias = colunas_fk.get(linha.nome, [])`,
      `chave_estrangeira=bool(referencias)`
- [x] `extractors/postgres/extrator_postgres.py` / `extractors/mariadb/extrator_mariadb.py`
      — atualiza chamada (sem desempacotar `avisos`)
- [x] Comentários desatualizados corrigidos em
      `domain/model/common/restricao_de_fk_composta.py` e
      `extractors/comum/construir_restricoes_fk_compostas.py`

## 3. ACL Extraction → Curation

- [x] `overrides/sobrescrita_de_tabela.py` — `_calcular_hash_estrutural`:
      troca a serialização de `coluna.referencia` por iteração sobre
      `coluna.referencias` (todas incluídas) — sem isso, FK extra
      adicionada/removida na mesma coluna não dispara aviso de estrutura
      alterada

## 4. Geradores

- [x] `generators/dbt/_testes.py` — só emite `relationships` quando
      `len(coluna.referencias) == 1`; quando `> 1`, emite `Aviso` de
      ambiguidade em vez de teste. Mantém a exclusão por
      `colunas_em_fk_composta`
- [x] `generators/markdown/_filtros.py` — `_marcadores_de_restricao`: um
      marcador `"FK → escopo.tabela.coluna"` por referência
- [x] `generators/contexto_de_ia/_grafo.py` — itera `coluna.referencias`,
      uma aresta `"referencia"` por FK (e `"referenciado_por"` simétrico
      do lado de destino, para cada uma)
- [x] `generators/contexto_de_ia/_serializacao.py` — `_serializar_coluna`:
      `"referencia"` vira `"referencias": [...]`, sempre presente

## 5. Testes

- [x] Unit: `test_construir_colunas_fk.py` reescrito — feliz (sem
      colisão), borda (2 FKs mesma coluna → lista com as duas, ordem
      preservada, sem `Aviso`), borda (lista vazia)
- [x] Unit: validator `_valida_referencia_de_chave_estrangeira` nos 3
      modelos — `chave_estrangeira=True`/`referencias=[]` continua
      inválido
- [x] Unit: `_construcao.py` dos dois extratores — coluna com 2+
      referências
- [x] Unit: `sobrescrita_de_tabela.py` — hash muda quando uma 2ª FK é
      adicionada/removida na mesma coluna
- [x] Unit: `GeradorDbt` — coluna com 1 referência gera teste
      (regressão); coluna com 2+ não gera teste `relationships`, gera
      `Aviso`
- [x] Unit: `GeradorMarkdown`/`GeradorContextoDeIA` — coluna com 2+
      referências lista todas
- [x] Integração: fixture nova reproduzindo o padrão real da issue
      (coluna com 2 FKs para tabelas diferentes) contra Postgres 16 **e**
      MariaDB 11 reais via `testcontainers`

## 6. Documentação

- [x] `docs/low_level_design.md` — schema dos 3 modelos, seção
      `construir_colunas_fk`, seções dos 3 Geradores (incl. decisão de
      supressão do teste dbt para FK polimórfica)
- [x] `plan/tasks.md` — entrada nova na seção 6

## Fora de escopo (avaliado e adiado)

- `OrquestradorParalelo`, Analisadores, Port `Extrator` — nenhuma
  mudança.
- Nenhuma query SQL nova nos dois Extratores.

## Efeito visível ao usuário (a registrar no PR)

Para as poucas colunas reais com esse padrão: Markdown ganha marcadores
`"FK → ..."` múltiplos na mesma coluna; artefato dbt deixa de gerar teste
`relationships` nessas colunas específicas (antes testava contra a
referência sobrevivente arbitrária — resultado silenciosamente incorreto)
e passa a emitir `Aviso` explicando a ambiguidade; contexto de IA lista
todas as referências.

## Verificação final

- [x] `mypy --strict` + `ruff check` limpos
- [x] `pytest` completo (unit + integration) verde
- [x] Rodar o wizard manualmente contra a fixture de integração nova
      (Postgres e MariaDB) e inspecionar os 3 artefatos gerados para a
      coluna polimórfica: Markdown mostra 2 marcadores FK, dbt não gera
      teste `relationships` + mostra `Aviso`, contexto de IA lista as 2
      referências em `"referencias"`

## Revisão pós-implementação (banca da verdade)

Após a implementação completa, a banca (arquiteto-de-software,
engenheiro-de-dados, po-revisor) revisou o **código de fato
implementado** (não mais o plano), em modo auto, sem permissão de
escrever. Veredito unânime: **aprovado** (2 limpos, 1 "aprovado com
ressalvas"). Nenhum achado bloqueante de correção, arquitetura ou
qualidade de dados. Achados e decisões:

- **Mensagem do `Aviso` do dbt densa para usuário não-técnico** (achado
  do engenheiro-de-dados e do PO, mesmo ponto independente): o texto
  original citava só termos técnicos (`where`/discriminator) sem
  explicar em linguagem simples o que está acontecendo. Primeira
  correção adicionou uma frase simples + o detalhe técnico completo (2
  listas redundantes: tabelas e colunas). **Revisado a pedido do
  usuário** (excessivamente longo na prática, testado contra base real)
  — mensagem final em frase única: conta + tabelas alvo (sem repetir a
  coluna referenciada, já óbvia) + motivo + orientação de teste manual.
- **Sem teste cobrindo 3+ referências** (achado do engenheiro-de-dados):
  o código generaliza corretamente (`len > 1`), mas nada provava a
  mensagem do `Aviso` com N > 2 alvos. **Aplicado:** teste novo em
  `test_gerador_dbt.py` com 3 referências.
- **Sentinel do hash estrutural mudou de `"None"` explícito para `""`
  implícito** (achado do arquiteto): ao trocar `Optional` por lista, o
  hash passou a serializar ausência de FK como string vazia em vez de um
  marcador distinto. Avaliação inicial (nenhuma coleta real de hashes em
  produção ainda) tratou como inofensivo e só documentou via comentário;
  **revisado a pedido do usuário** — sem hash real persistido em
  `overrides/*.yaml` pra proteger, não há motivo pra aceitar a
  ambiguidade "por precaução". **Aplicado:** `_calcular_hash_estrutural`
  volta a emitir o sentinel explícito `"None"` quando `referencias` está
  vazia (mesmo texto da versão singular pré-#105), removendo o
  comentário que só explicava por que a ambiguidade era tolerável.
- **Heurística de coluna discriminator** (pergunta do engenheiro-de-dados
  ao PO): detectar/sugerir automaticamente qual coluna funciona como
  discriminator de uma FK polimórfica. **Avaliado e adiado** — heurística
  nova, escopo maior que esta issue, mesmo critério de #95/#104 pra
  sugestões descartadas. Não virou issue formal; registrado aqui como
  ideia caso o usuário queira retomar no futuro.
- **`plan/registry-plan/issue-105-*.md` estava untracked** (apontado pelo
  PO como bloqueante de critério de aceite): esperado neste momento —
  commits ficam sob decisão explícita do usuário, nunca automáticos.

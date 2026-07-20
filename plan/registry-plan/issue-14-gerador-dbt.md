# Issue #14 — feat: GeradorDbt

## Contexto

Fase 6 de `plan/global.md` (Geradores concretos), segunda sub-issue.
`GeradorDbt` produz um projeto dbt standalone (staging layer) a partir do
`BancoAnalisado` — o pitch principal do produto (`docs/prd.md`). A pendência
registrada pela #44 ("`GeradorDbt` deve priorizar `nao_nulavel`/`unica` sobre
a heurística amostral") foi resolvida aqui, na primeira implementação, em vez
de virar dívida técnica corrigida depois.

## Banca acionada sobre o desenho (antes de implementar)

Arquiteto de Software + Engenheiro de Dados + PO, mesmo padrão das #11/#13/
#44. Veredito: **Aprovado com ressalvas**, incorporadas ao desenho antes do
código.

> **Nome do staging model: `stg_<escopo>__<tabela>`, não `stg_<tabela>`
> (desvio do texto literal da issue, aprovado pelas 3 bancas).** Nomes de
> model são globalmente únicos no grafo dbt — `stg_<tabela>` sozinho
> colidiria se dois escopos tiverem tabela de mesmo nome (ex.:
> `vendas.clientes` e `rh.clientes`). Convenção real do dbt-labs para
> múltiplas fontes é o duplo underscore. Engenheiro de Dados confirmou que
> não é over-engineering: é o caminho padrão pra evitar exatamente essa
> colisão.

> **`relationships` aponta para `ref()` do staging model, não `source()`,
> e só quando a tabela referenciada está no lote analisado nesta execução
> (Engenheiro de Dados).** Testar contra `source()` bypassa o cast/staging;
> `ref()` é a prática correta. Quando a FK aponta pra fora do lote (ex.:
> usuário extraiu só um escopo), gerar `ref()` pra um model inexistente
> quebraria `dbt run` do usuário sem aviso — pior para a experiência do que
> um `Aviso` explícito e a omissão do teste (confirmado pelo PO como leitura
> correta do NFR1 do PRD: "nada aplicado por trás do usuário").

> **`unique`/`not_null` combinam o fato estrutural do schema
> (`coluna.unica`/`nao_nulavel`) com a métrica amostral, em vez de só a
> métrica (desvio do texto literal da issue, decisão do usuário).** Resolve
> a pendência deixada pela #44: sugerir `not_null`/`unique` só a partir de
> `percentual_nulo`/`percentual_unico` amostral tem o mesmo viés estatístico
> que motivou aquela issue — uma amostra pequena ou enviesada pode não bater
> 100%/0% exatos mesmo quando o schema garante a restrição de verdade. Mesmo
> padrão de "combinar fato estrutural com métrica só na apresentação" já
> usado pelo `GeradorMarkdown`.

> **`accepted_values` usa `config: {severity: warn}`, não o `error` padrão
> do dbt (ressalva do Engenheiro de Dados, decisão do usuário).**
> `valores_frequentes` é top-10 calculado sobre a **amostra**, não a
> população — `accepted_values` no dbt testa enumeração exaustiva contra a
> população real. Um valor de cauda longa fora da amostra (ou o 11º valor
> mais frequente de verdade) quebraria esse teste em CI mesmo com o dado
> correto e a coluna legitimamente categórica. `severity: warn` deixa o
> teste rodar e sinalizar, sem falhar o build silenciosamente por um sinal
> parcial.

> **Ressalva incorporada após a primeira verificação manual (usuário,
> revendo o artefato gerado): `severity: warn` sozinho não bastava —
> faltava um segundo critério baseado em cobertura.** O Engenheiro de
> Dados já tinha sugerido (nice-to-have) um tamanho mínimo de amostra;
> revisitado com o usuário, a escolha final foi mais precisa: em vez de
> olhar `tamanho_amostra` da tabela isoladamente, `_cobertura_dos_
> valores_frequentes` soma as contagens dos top-10 e divide pelo
> `tamanho_amostra` — só sugere `accepted_values` quando essa cobertura é
> ≥90%. Mede diretamente se a lista de top-10 é quase exaustiva dentro da
> própria amostra, em vez de usar o tamanho da amostra como proxy indireto.

> **CAST de ENUM/SET (vindos do MariaDB, issue #35) cai para `VARCHAR`
> (confirmado pelo Engenheiro de Dados).** Sem equivalente ANSI portável, e
> o ddf não conhece o warehouse de destino — melhor não fazer um CAST
> inseguro do que inventar um tipo específico de motor.

## Escopo desta issue

- [x] `GeradorDbt(Gerador)` — `requer = [MetricasBaseColuna]`,
      `src/ddf/infrastructure/adapters/generators/gerador_dbt.py`
- [x] `dbt_project.yml` — scaffold mínimo fixo (`ddf_staging`,
      `+materialized: view` em staging)
- [x] `models/staging/sources.yml` — um `source:` por escopo distinto do
      lote, tabelas ordenadas por `(nome_escopo, nome_tabela)`
- [x] `models/staging/stg_<escopo>__<tabela>.sql` por tabela — `SELECT` com
      `CAST` explícito + alias por coluna, via `TipoDeDado.categoria` +
      atributos de precisão (`_tipo_sql`); categoria `UNKNOWN` passa raw,
      sem CAST
- [x] `models/staging/schema.yml` — testes sugeridos deterministicamente:
      `unique`/`not_null` (métrica amostral OU fato estrutural, suprimidos
      quando PK), `relationships` (só com tabela referenciada no lote,
      senão `Aviso` + omissão), `accepted_values` (`percentual_unico<10.0`
      + `valores_frequentes` não vazio + cobertura da amostra ≥90%,
      `severity: warn`)
- [x] Identificadores do artefato (nomes de coluna/tabela, vocabulário de
      teste `unique`/`not_null`/`relationships`/`accepted_values`) em
      inglês — única exceção à nomenclatura em português
- [x] Refactor: `_escrever_arquivo` extraído para
      `generators/_escrita.py` (compartilhado com `GeradorMarkdown`) —
      `GeradorContextoDeIA` (próximo Gerador, já documentado no LLD) seria
      o 3º consumidor duplicando a mesma função

## Testes

- [x] `tests/unit/.../generators/test_gerador_dbt.py` — 7 testes: caminho
      feliz (2 tabelas, 2 escopos, as 4 regras de teste disparando em
      colunas diferentes, CAST correto, nome de arquivo
      `stg_<escopo>__<tabela>.sql`); erro de escrita em disco; borda (coluna
      sem métrica e sem fato estrutural → sem `tests:`); FK fora do lote →
      `Aviso` + sem `relationships`; `accepted_values` omitido quando o
      top-10 cobre pouco da amostra (categórica, mas cobertura < 90%);
      categoria `UNKNOWN` sem CAST; determinismo (mesma entrada → arquivos
      byte-a-byte idênticos em duas execuções)
- [x] `pytest` (263 passed), `mypy --strict src` (49 arquivos, 0 erros),
      `ruff check` limpos

## Achado na verificação manual (pós-implementação, antes do commit)

> **Bug real no template SQL: linhas de coluna coladas numa única linha,
> sem quebra antes do `FROM`.** O template usava
> `{{ coluna.expressao }} as {{ coluna.nome }}{% if not loop.last %},{% endif %}`
> — como a linha termina em `{% endif %}` (uma tag de bloco) e o ambiente
> Jinja2 usa `trim_blocks=True` (mesma configuração do `GeradorMarkdown`),
> a quebra de linha logo após `%}` era engolida, colando todas as colunas
> numa linha só. Os testes automatizados não pegaram porque as asserções
> originais checavam substring (`"CAST(email AS VARCHAR(255)) as email" in
> sql`), que continua verdadeira mesmo com as linhas coladas. **Achado**
> inspecionando visualmente o `.sql` gerado contra um `BancoAnalisado` de
> teste real (passo de verificação manual do plano, não fixture de teste).
> **Corrigido:** a vírgula de separação passou a ser computada em Python
> (`coluna["sufixo"]`) em vez de lógica condicional inline no template — a
> linha de conteúdo termina em `{{ coluna.sufixo }}` (substituição de
> variável, não tag de bloco), preservando a quebra de linha. Teste de
> caminho feliz reforçado para checar linha a linha, não só substring.

## Achados da banca de revisão de código (diff completo, antes do commit)

Rodada extra além da revisão de plano: arquiteto-de-software, engenheiro de
dados e PO revisaram o diff de verdade (nada staged ainda). Veredito:
**Aprovado** (arquiteto e PO) / **Aprovado com ressalvas** (engenheiro de
dados) — uma ressalva revelou um bug estatístico real, corrigida antes do
commit.

> **Bug real: viés de denominador em `_cobertura_dos_valores_frequentes`
> (Engenheiro de Dados).** A função dividia a soma dos top-10
> `valores_frequentes` pelo `tamanho_amostra` **total**, mas
> `valores_frequentes` é calculado só sobre valores **não-nulos**
> (`AnalisadorDeMetricasDeColuna` usa `serie.drop_nulls()`). Numa coluna
> categórica com muitos nulos (ex.: 60% nula, mas os 40% não-nulos cobertos
> 100% pelo top-10), a cobertura calculada ficava artificialmente baixa
> (40%), abaixo do limiar de 90%, suprimindo `accepted_values`
> injustamente mesmo com enumeração exaustiva sobre o universo real de
> valores presentes. Efeito era conservador (nunca gerava teste incorreto,
> só deixava de sugerir um válido), mas era uma lacuna estatística real, não
> hipotética. **Corrigido:** denominador passou a ser
> `tamanho_amostra * (1 - percentual_nulo / 100)` (contagem de não-nulos),
> não o total da amostra. Novo teste
> (`test_accepted_values_considera_apenas_nao_nulos_no_denominador`) cobre
> exatamente esse cenário — 60% nula, top-10 exaustivo sobre os não-nulos,
> confirma que `accepted_values` volta a ser sugerido.

> **Nice-to-haves não bloqueantes, registrados mas não implementados nesta
> issue:** `_DBT_PROJECT` (`name`/`profile: "ddf_staging"`) é fixo, sem
> parametrização por projeto (Arquiteto) — aceitável pro escopo atual de
> "um projeto dbt por execução"; `_sugestoes_de_teste` já está no limite de
> tamanho pra acomodar um 5º tipo de teste sem quebrar em funções menores
> (Arquiteto); threshold de 90% de `accepted_values` é fixo e não
> configurável (Engenheiro de Dados) — mitigado pelo `severity: warn` já
> combinado; artefato gerado não expõe ao usuário final *por que* um teste
> específico não apareceu — só o código/este registro explicam (PO).

## Pendências para próximas issues (não resolvidas aqui)

- **`GeradorContextoDeIA` (próximo Gerador da Fase 6)** deve reusar
  `generators/_escrita.py`, já extraído nesta issue.
- **ENUM com `valores_permitidos` preenchido poderia dimensionar
  `VARCHAR(n)`** pelo maior valor permitido, em vez de `VARCHAR` sem
  tamanho — sugestão nice-to-have do Engenheiro de Dados, fora do escopo
  literal da issue.

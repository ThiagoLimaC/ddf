# Issue #56 — fix: corrige achados bloqueantes e sugestões da auditoria de engenharia de dados

## Contexto

Após a revisão arquitetural pré-CLI (#53), uma auditoria completa pela lente
de engenharia de dados (agente `engenheiro-de-dados`), validada
empiricamente contra Postgres 15 e MariaDB 11 reais, encontrou achados
bloqueantes e sugestões que precisam ser resolvidos antes da Task 7 (CLI/
wizard). Consolidados em 4 fases nesta issue.

## Decisões tomadas na discussão prévia (antes de implementar)

> **`ARRAY` do Postgres — categoria própria, não `UNKNOWN` (revisto em
> relação à decisão original da issue).** A decisão original do PO era só
> falha graciosa (`UNKNOWN`), suporte semântico pleno fora de escopo da v1.
> Revisitado pelo usuário durante o planejamento: `CategoriaDeDado.ARRAY`
> nova + atributo `elemento: CategoriaDeDado | None` em `TipoDeDado` (sem
> precisão do elemento — opção "leve", não um tipo recursivo). Cobre
> `udt_name` do Postgres (não lido antes), mapeia pro elemento quando
> reconhecido, cai em `elemento=None` quando não.
> **`relationships` do dbt em FK composta — documentar a limitação, não
> modelar FK composta de verdade.** Modelar de verdade exigiria agrupar
> colunas de uma mesma constraint composta no Extraction Context (hoje
> `referencia` é por coluna) — mudança bem maior que as outras 4 sugestões
> da Fase 2, tocando 3 Bounded Contexts. A própria issue aceita documentar
> como saída válida. Confirmado com o usuário (PO).
> **Otimização N+1 (Fase 4) revisada com o `engenheiro-de-dados`:** filtro
> `relkind IN ('r', 'p')` em `_TOTAL_LINHAS_SQL` (bug pré-existente, não
> introduzido aqui — tabela particionada é `BASE TABLE` em
> `information_schema.tables`, mas `reltuples` do pai só agrega os filhos a
> partir do PG14). Medição de throughput com 50-100+ tabelas reais fica
> limitada a um piso conservador via testcontainers local (sem Postgres
> gerenciado disponível neste ambiente) — documentado explicitamente como
> tal, não como a medição de produção que o critério de aceite original
> pede.

Plano completo de implementação: `/home/dev/.claude/plans/cosmic-exploring-matsumoto.md`
(sessão de planejamento com Claude, 2026-07-21).

## Escopo desta issue

### Fase 1 — bugs bloqueantes 

- [x] `AnalisadorDeMetricasDeColuna`: normalização de série (antes só
      `pl.Object`) cobre `pl.List` também — corrige `InvalidOperationError`
      de `.min()`/`.max()` em coluna `ARRAY`; funções renomeadas para
      `_normalizar_serie_nao_nativa`/`_representar_valor_nao_nativo`
- [x] `TipoDeDado`: `CategoriaDeDado.ARRAY` + atributo `elemento:
      CategoriaDeDado | None`
- [x] `mapear_tipo_postgres`: refatorado pra despachar por `udt_name`
      (nome canônico de uma palavra por tipo), não mais por `data_type`
      (multi-word) — elimina tabela duplicada, `_CATEGORIAS_SIMPLES` serve
      tanto de fallback do tipo externo quanto de resolução do `elemento`
      do `ARRAY`; detecção de array via prefixo `"_"` do `udt_name`
- [x] `ExtratorPostgres`: `udt_name` na query de colunas (substitui
      `data_type`, agora sem uso), repassado até o mapeamento
- [x] `GeradorMarkdown`/`GeradorDbt`: renderizam `ARRAY` (`"<ELEMENTO>[]"`
      no Markdown, `CAST(col AS <ELEMENTO>[])` no dbt quando elemento
      conhecido; passthrough sem `CAST` quando não — `_tem_cast_seguro`
      substitui a checagem que antes só olhava `UNKNOWN`)
- [x] `ExtratorMariaDB`: nova query em `information_schema.CHECK_CONSTRAINTS`
      + `_extrair_coluna_json_valid` (função pura, regex, validada contra
      MariaDB 11 real) — corrige `JSON` classificado como `TEXT`;
      `CHECK_CONSTRAINTS` não tem `TABLE_NAME`, defesa via cruzamento com
      colunas reais da tabela (`_colunas_json_de_check_clauses`); entrada
      morta `"json"` removida de `_CATEGORIAS_SIMPLES` do MariaDB
- [x] `mypy --strict`/`ruff` limpos
- [x] Testes unit + integração (testcontainers Postgres 16 e MariaDB 11
      reais) — caminho feliz, erro esperado, borda; inclui teste ponta a
      ponta Extrator → Sobrescrita → `AnalisadorDeMetricasDeColuna` contra
      Postgres real reproduzindo o crash original

### Fase 3 — boundary sistemático de exceção (bloqueante) 

- [x] `pipeline/seguranca.py` — `executar_com_seguranca(nome_estagio,
      funcao) -> Resultado`; testada isoladamente (`test_seguranca.py`)
- [x] Aplicada em `compor()` (nomeia pelo tipo/`__name__` do Estagio),
      `OrquestradorParalelo._executar_em_paralelo` (novo parâmetro
      `nome_estagio`, combinado com o identificador do item na mensagem;
      `extrair` passa `"Extrator"`, `aplicar_sobrescritas` passa
      `"Sobrescrita"`) e `scripts/prototipo_wizard_mariadb.py` (as 3
      chamadas de Gerador)
- [x] Nova Decisão de Arquitetura 12 em `docs/system_design_doc.md`
- [x] Notas no `low_level_design.md` (`compor`, `OrquestradorParalelo` e
      seção CLI — Task 7 obrigada a repetir o padrão em torno de cada
      Gerador)
- [x] Testes: exceção não prevista em `compor()` vira `Falha` sem rodar
      Estagios seguintes; exceção em worker de `OrquestradorParalelo`
      acumula como falha isolada sem quebrar o lote; nenhuma regressão nos
      casos de `Falha` explícita já testados

### Fase 2 — sugestões de qualidade ✅ concluída

- [x] Completude/percentuais distinguem "sem evidência" (amostra vazia) de
      "0% nulo" na apresentação (`GeradorMarkdown._formatar_completude`/
      `_linha_qualidade`, `GeradorContextoDeIA` ganha `amostra_vazia: bool`
      ao lado de `completude`); `GeradorDbt._sugestoes_de_teste` exige
      `tamanho_amostra > 0` antes de considerar a métrica amostral pra
      `unique`/`not_null` (fato estrutural do schema continua valendo)
- [x] `Aviso` quando `tamanho_amostra > total_linhas` em ambos os
      Extratores — sintoma de `reltuples`/`TABLE_ROWS` desatualizado
- [x] Custo de amostragem full-scan documentado em `PercentualDeLinhas`,
      `EstrategiaDeAmostragem` e `system_design_doc.md` (que também corrigiu
      menção desatualizada a `LimiteAleatorio`, substituída há tempos por
      `PercentualDeLinhas`)
- [x] Limitação de `relationships`/FK composta documentada em
      `_sugestoes_de_teste` (`gerador_dbt.py`) e `low_level_design.md` —
      decisão de documentar, não modelar FK composta de verdade
- [x] `generated_at` (ISO 8601, `datetime.now(UTC)`) em `GeradorMarkdown`
      (rodapé de `index.md` e de cada `.md` de tabela), `GeradorDbt`
      (`dbt_project.yml`, bloco `meta`) e `GeradorContextoDeIA`
      (`index.json`, chave de topo) — os dois testes de determinismo
      byte-a-byte já existentes foram ajustados pra excluir esse campo
      (variável por natureza) da comparação, mantendo o resto do artefato
      comparado normalmente

### Fase 4 — otimização N+1 (não bloqueante)

- [ ] Cache por schema em `ExtratorPostgres` (double-checked locking, mesmo
      padrão de `_obter_pool`), 4 queries de metadado consolidadas por
      schema
- [ ] Filtro `relkind IN ('r', 'p')` em `_TOTAL_LINHAS_SQL`
- [ ] Benchmark sintético via testcontainers (10/50/100/200 tabelas, 3-5
      schemas) com ressalva de piso conservador documentada no PR

## Testes

- [ ] Fase 1: unit + integração (testcontainers Postgres/MariaDB reais) —
      caminho feliz, erro esperado, borda por item
- [ ] Fase 3: `compor()`/`OrquestradorParalelo` com exceção não prevista
      virando `Falha`, sem regressão dos casos de `Falha` explícita já
      testados
- [ ] Fase 2: casos novos nos testes já existentes dos Geradores/Extratores
      afetados
- [ ] Fase 4: thread-safety do cache por schema + corretude ponta a ponta
- [ ] `pytest` completo (unit + integration) verde antes do PR

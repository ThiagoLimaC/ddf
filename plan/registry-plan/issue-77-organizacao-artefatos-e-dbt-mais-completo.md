# Issue #77 — organização por diretório + mini projeto dbt mais completo

## Parte 1 — Bugfix: subpasta por Gerador sempre

- [x] `geracao.py`: `executar_geradores` escreve cada Gerador em
      `destino/<slug>`; `sugerir_destino` removida (indireção morta uma vez
      que o subpath deixa de ser caso especial)
- [x] `wizard.py`: destino sugerido no prompt vira `"artefatos"` fixo
- [x] `test_geracao.py`: remove testes de `sugerir_destino`, atualiza
      `GeradorFake` pra gravar destino recebido, testes de
      `executar_geradores` cobrindo subpastas separadas (repro do bug) e
      slug CamelCase
- [x] `docs/low_level_design.md`: atualiza descrição da etapa 12

## Parte 2 — `GeradorDbt`: README.md + subpastas por escopo

- [x] `gerador_dbt.py`: `sources.yml`/`*.sql`/`schema.yml` por escopo em
      `models/staging/<escopo>/`; `README.md` na raiz do projeto gerado;
      `_agrupar_por_escopo` extraído como helper compartilhado entre
      `_montar_sources`/`_renderizar_readme` (reuso real, mesmo loop)
- [x] `templates/readme.md.jinja2` novo
- [x] `test_gerador_dbt.py`: paths atualizados por escopo, teste de
      README.md, teste de dois escopos não vazando tabela entre si
- [x] `test_wizard_end_to_end.py`: path do artefato Markdown corrigido
      (consequência da Parte 1)

## Parte 3 — `GeradorContextoDeIA`: subpasta por escopo (pedido do usuário, extensão do mesmo padrão)

- [x] `gerador_contexto_de_ia.py`: `tabelas/<escopo>/<tabela>.json` em vez
      de achatado `tabelas/<escopo>__<tabela>.json` — sem prefixo de escopo
      no nome do arquivo (a subpasta já desambigua; diferente do
      `GeradorDbt`, que precisa de nome globalmente único no grafo dbt)
- [x] `test_gerador_contexto_de_ia.py`: paths atualizados
- [x] `docs/low_level_design.md`: seção do `GeradorContextoDeIA` atualizada

## Fora de escopo (registrar como issue futura)

- `packages.yml`/`dbt_utils` — exigiria UNIQUE composto estrutural
  (campo novo em `TabelaExtraida`/`TabelaCurada`/`TabelaAnalisada`, query
  nova em `ExtratorPostgres`/`ExtratorMariaDB`, hash estrutural), mesmo
  tratamento já dado à FK composta
- Camada intermediate, `profiles.yml`
- `analyses/`, `exposures.yml`, `freshness` em sources — dependem de
  informação que o `BancoAnalisado` não carrega hoje (queries
  exploratórias, consumidores finais, coluna confiável de atualização)
- Macros custom em `macros/` — candidatas levantadas na revisão da #77,
  ainda sem issue própria:
  - Teste genérico validando `formato_detectado` (email/CPF/CNPJ/telefone/
    CEP) via regex — métrica hoje calculada pelo
    `AnalisadorDeMetricasDeColuna` mas nunca consumida pelo `GeradorDbt`
  - Teste "soft" (`severity: warn`) de taxa de nulos/unicidade pra colunas
    sem `not_null`/`unique` estrutural mas com `percentual_nulo`/
    `percentual_unico` baixo na amostra — hoje só testa quando bate
    exatamente 0%/100%

## Verificação final

- [ ] `mypy --strict` + `ruff check`
- [ ] `pytest tests/unit/infrastructure/adapters/cli/etapas/test_geracao.py
      tests/unit/infrastructure/adapters/generators/test_gerador_dbt.py`
- [ ] `plan/tasks.md` atualizado com reabertura de escopo #77

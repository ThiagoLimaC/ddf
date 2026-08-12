# Issue #93 — renderiza UNIQUE composto em Markdown/IA

Plano completo revisado em `/home/dev/.claude/plans/noble-forging-reef.md`
(sessão de planejamento). Banca de revisão (arquiteto-de-software +
engenheiro-de-dados + po-revisor) rodada sobre o plano antes da
implementação, apesar de a própria issue classificar o escopo como pequeno
e dispensar banca completa. Todos aprovaram a abordagem; decisões abaixo
incorporam os achados.

Fecha a assimetria apontada pelo PO na revisão da #89: `restricoes_unicas`
(campo de nível tabela, issue #89) só era consumido pelo `GeradorDbt`.
`GeradorMarkdown`/`GeradorContextoDeIA` não o renderizavam, apesar de já
renderizarem o análogo single-column (`unica`).

Decisões fechadas com a banca:

- Markdown recebe **dois** pontos de renderização, não um: marcador
  `"UNIQUE (composto)"` por coluna em `_marcadores_de_restricao` (achado
  do engenheiro-de-dados — só o bullet deixava quem escaneia a tabela de
  colunas sem sinal de participação) + bullet em "Fatos extraídos" com os
  grupos completos.
- Filtro Jinja novo nomeado `formatar_restricoes_unicas` (não
  `restricoes_unicas` — colidiria em legibilidade com o atributo do
  próprio modelo no mesmo template; achado do arquiteto).
- Nomes de coluna escapados e envolvidos em crase no bullet (identificador
  do Postgres pode conter caractere que quebra ênfase Markdown; achado do
  engenheiro-de-dados).
- `RestricaoUnica`s ordenadas deterministicamente (`sorted` por tupla de
  colunas) no ponto de renderização/serialização dos dois Geradores novos
  — ordem de origem vem do catálogo (OID), estável mas sem significado
  humano; sem ordenar, reextrações do mesmo schema lógico geram diff
  espúrio em artefato versionado no Git (achado do engenheiro-de-dados).
  `GeradorDbt` não é tocado — mantém a ordem atual, fora de escopo.
- `GeradorContextoDeIA`: `restricoes_unicas: list[list[str]]` na raiz do
  JSON da tabela (não dentro de `esquema_de_consulta`, reservado a
  heurística de amostra), chave omitida quando vazia (mesma convenção de
  `metricas_tabela`). Lista de listas em vez de dict nomeado — decisão
  explícita na docstring: `RestricaoUnica` só carrega `colunas`, sem
  metadado adicional que justifique um wrapper.

## 1. `GeradorMarkdown`

- [x] `_marcadores_de_restricao`: novo marcador `"UNIQUE (composto)"` para
      coluna presente em algum `RestricaoUnica` da tabela
- [x] `_formatar_restricoes_unicas(tabela) -> str`, filtro
      `formatar_restricoes_unicas`, nomes escapados + entre crase, grupos
      ordenados
- [x] `templates/tabela.md.jinja2`: bullet condicional em "Fatos
      extraídos", logo após "Amostra analisada"

## 2. `GeradorContextoDeIA`

- [x] `_montar_tabela_json`: `restricoes_unicas` (lista de listas,
      ordenada, omitida se vazia) com docstring justificando o formato

## 3. Testes

- [x] `test_gerador_markdown.py`: `_formatar_restricoes_unicas` (1
      restrição, 2+, lista vazia); `_marcadores_de_restricao` com coluna em
      restrição composta; renderização do template com/sem
      `restricoes_unicas`, checando posição do bullet
- [x] `test_gerador_contexto_de_ia.py`: `_montar_tabela_json` com
      `restricoes_unicas` presente (ordenada) e ausente (chave omitida)

## 4. Documentação

- [x] `plan/tasks.md` — reabertura de escopo da #89 na seção 6

## Fora de escopo (confirmado pela banca)

- `GeradorDbt` — já consome desde a #89, não muda aqui.
- Modelo (`RestricaoUnica`, `TabelaAnalisada`), Extratores, Analisadores —
  nenhuma mudança.
- FK composta / reavaliação de `_sugestoes_de_teste` — pertence à #95.

## Verificação final

- [x] `mypy --strict` (73 arquivos em `src/`) + `ruff check` (`src` +
      `tests`) — limpos
- [x] `pytest tests/unit` — 446 testes passando, sem regressão
- [x] Geração manual de artefato Markdown/IA contra fixture com UNIQUE
      composto (2 restrições em ordens diferentes), inspeção visual do
      bullet/marcador/JSON — grupos ordenados corretamente, bullet e
      marcador de coluna consistentes entre si

# Issue #6 — feat: Extraction e Curation Context

- [x] `domain/model/extraction.py`
  - `ColunaExtraida` — `nome`, `tipo_dado: TipoDeDado`, `chave_primaria`,
    `chave_estrangeira`, `tabela_referenciada`, `coluna_referenciada`
  - `TabelaExtraida` — `nome_tabela`, `nome_schema`, `colunas: list[ColunaExtraida]`,
    `total_linhas`, `amostra: pl.DataFrame | None`, `metadados_amostra`;
    `model_config = ConfigDict(arbitrary_types_allowed=True)`
  - `ColunaExtraida` sem `frozen=True` — fiel ao snippet do low_level_design.md,
    que não pede imutabilidade aqui (diferente de `TipoDeDado` na #5, que tinha
    texto explícito "imutável após construção")
  - **`amostra: pl.DataFrame` (não `| None`)** — o snippet original do
    low_level_design.md tornava opcional com o comentário "None após o
    Analisador descartar", mas o Analisador nunca vê `TabelaExtraida` (só
    `TabelaCurada`, via `ContextoDeAnalise.curado`). Inconsistência encontrada
    e corrigida com o usuário: obrigatório em `TabelaExtraida` (Extrator
    sempre preenche), opcional só em `TabelaCurada` (onde o Analisador de fato
    descarta). `low_level_design.md` corrigido também

- [x] `domain/model/curation.py`
  - `ColunaCurada` — mesmos campos de `ColunaExtraida` + `papel_de_negocio`,
    `regras_de_negocio: list[str]`
  - `TabelaCurada` — mesma estrutura de `TabelaExtraida` com `colunas: list[ColunaCurada]`
    + `papel_de_negocio`, `regras_de_negocio`; `arbitrary_types_allowed=True`
  - `BancoCurado` — `tabelas: list[TabelaCurada]`; `arbitrary_types_allowed=True`
  - `papel_de_negocio`/`regras_de_negocio` ganharam `Field(description=...)` em
    `ColunaCurada` e `TabelaCurada` — não estava no snippet original, mas os
    nomes são ambíguos sem contexto ("o que o dado significa" vs. "quais
    regras se aplicam"); decisão do usuário

- [x] Testes: `tests/unit/domain/model/test_extraction.py`,
      `tests/unit/domain/model/test_curation.py` — caminho feliz, erro esperado
      e borda por modelo
  - Fixture de `pl.DataFrame` mínimo em conftest para popular `amostra` sem
    depender de nenhum Extrator concreto (ainda não existe — issue #9)
  - `conftest.py` novo em `tests/unit/domain/model/` (nível de pasta, não
    `common/`) — compartilhado entre `test_extraction.py` e `test_curation.py`

- [x] `mypy --strict` + `ruff` limpos

## Correções de validação encontradas durante a revisão

Achados na revisão de critérios de aceite dos modelos (extraction/curation e,
retroativamente, common da #5). Ordem de dependência para implementação e
commits: `common` → `extraction` → `curation`.

- [x] `domain/model/common/tipo_de_dado.py` — `TipoDeDado`: rejeitar
      combinações inconsistentes de atributos por `CategoriaDeDado`
      (ex.: `precisao`/`escala` só fazem sentido em `NUMERIC`;
      `tamanho_maximo` só em `VARCHAR`; demais categorias não aceitam nenhum
      atributo extra)
  - `model_validator(mode="after")` com dicionário `_ATRIBUTOS_PERMITIDOS`
    (categoria → atributos aceitos), extensível sem reescrever lógica
  - Regra adicional decidida com o usuário: `escala` sem `precisao` é
    inconsistente (`NUMERIC(10)` sem escala é válido em SQL — escala 0
    implícita —, mas escala sem precisão não existe)
  - Testes em `tests/unit/domain/model/common/test_tipo_de_dado.py`: erro
    esperado por categoria incompatível (INTEGER+tamanho_maximo,
    VARCHAR+precisao, NUMERIC+tamanho_maximo, NUMERIC com escala sem
    precisao) + borda (NUMERIC só com precisao, sem escala)
- [x] `domain/model/common/metadados_de_amostra.py` — `MetadadosDeAmostra`:
      `tamanho_amostra >= 0` e `total_linhas >= 0` (via `Field(ge=0)`)
  - `total_linhas` de `MetadadosDeAmostra` esclarecido: **não é duplicata** de
    `TabelaExtraida.total_linhas`. Representa o universo considerado pela
    `EstrategiaDeAmostragem` (hoje coincide com o total real porque
    `LimiteAleatorio` não filtra; estratégia futura com filtro divergiria, e
    isso pode virar critério de seleção na CLI). `low_level_design.md`
    atualizado com essa distinção
  - Testes em `test_metadados_de_amostra.py`: erro esperado (negativo em cada
    campo) + borda (`0` aceito em ambos — tabela vazia é estado real)
- [x] `domain/model/common/configuracao_de_extracao.py` —
      `ConfiguracaoDeExtracao`: `max_trabalhadores > 0` e `max_conexoes > 0`
      (valor zero ou negativo de workers/conexões não tem sentido operacional)
  - `Field(gt=0)`, não `ge=0` — diferente de `MetadadosDeAmostra.total_linhas`,
    aqui `0` não é um estado real observável, é config inutilizável
  - Testes em `test_configuracao_de_extracao.py`: erro esperado
    (`max_trabalhadores=0`, `max_conexoes` negativo) + borda (ambos `=1`,
    menor valor operacionalmente válido)
- [x] `domain/model/extraction.py`
  - `ColunaExtraida`: `chave_estrangeira=True` exige `tabela_referenciada` e
    `coluna_referenciada` preenchidos (e vice-versa — referência preenchida
    sem `chave_estrangeira=True` também é rejeitada)
  - `TabelaExtraida`: `total_linhas >= 0` (`Field(ge=0)`); nomes em `colunas`
    únicos (`model_validator`, mensagem lista os nomes duplicados)
  - Decisão discutida: lógica de validação **duplicada** entre
    `ColunaExtraida`/`ColunaCurada` (não extraída para helper compartilhado)
    — mesmo a regra do CLAUDE.md falando de "tipos", extrair função
    utilitária cruzando contextos foi considerado uma invasão de Bounded
    Context indesejada pelo usuário
  - Testes em `test_extraction.py`: erro esperado (FK sem referência,
    referência sem FK, `total_linhas` negativo, colunas duplicadas) + removidos
    os 3 testes genéricos de Pydantic já identificados
- [x] `domain/model/curation.py`
  - `ColunaCurada`: mesma regra de FK consistente de `ColunaExtraida`
  - `TabelaCurada`: `total_linhas >= 0`; nomes em `colunas` únicos
  - `BancoCurado`: `(nome_schema, nome_tabela)` únicos em `tabelas` — regra
    nova, sem equivalente em `TabelaExtraida`/`ColunaExtraida` (só existe
    porque `BancoCurado` é o agregado que junta múltiplas tabelas, produzido
    pelo `OrquestradorParalelo`)
  - `test_cria_banco_curado_com_multiplas_tabelas` corrigido: usava a mesma
    `TabelaCurada` duas vezes, o que agora é rejeitado pela nova regra;
    passou a usar duas tabelas distintas (`pedidos`/`clientes`)
  - Testes em `test_curation.py`: erro esperado (FK sem referência, referência
    sem FK, `total_linhas` negativo, colunas duplicadas, tabelas duplicadas
    no `BancoCurado`); reagrupados por modelo e categoria (feliz/erro/borda)
- [x] Revisão de utilidade dos testes existentes: removidos os que só
      protegiam comportamento genérico do Pydantic (campo obrigatório
      ausente, lista vazia aceita) sem regra de negócio por trás — mesmo
      critério aplicado na #5:
  - `test_extraction.py::test_coluna_extraida_sem_tipo_dado_levanta_validation_error`
  - `test_extraction.py::test_tabela_extraida_sem_metadados_amostra_levanta_validation_error`
  - `test_extraction.py::test_tabela_extraida_sem_colunas_e_aceita`
  - `test_curation.py::test_coluna_curada_sem_tipo_dado_levanta_validation_error`
  - `test_curation.py::test_tabela_curada_sem_metadados_amostra_levanta_validation_error`
  - `test_curation.py::test_banco_curado_sem_tabelas_levanta_validation_error`
  - `test_curation.py::test_banco_curado_com_lista_vazia_e_aceito`
  - Testes de constraint (`Field(ge=0)`, `Field(gt=0)`) mantidos: não são
    comportamento genérico do Pydantic, e sim regra de negócio nossa
    codificada como constraint — mesmo raciocínio já aplicado a
    `max_conexoes >= max_trabalhadores` na #5
  - `test_extraction.py::test_tabela_extraida_sem_colunas_e_aceita` também
    removido (mesmo critério, identificado numa segunda passada)
  - `test_extraction.py` e `test_curation.py` reagrupados por categoria
    global (todos os caminho feliz juntos, depois erro esperado, depois
    borda) em vez de agrupados por modelo — `TabelaExtraida` ficou sem teste
    de borda próprio: nenhuma borda real sobrou além da já coberta em
    `ColunaExtraida`, e não foi criado um substituto artificial só para
    preencher a categoria
- [x] `mypy --strict` + `ruff` limpos

## Fora do escopo desta issue

- `EstrategiaDeAmostragem` e `ConfiguracaoDeExtracao` — já entregues na #5
- `Extrator` (Port) e `ExtratorPostgres` (adapter) — issue #9 (task 3)
- `SobrescritaDeTabela` e `OrquestradorParalelo` — issue #7 (task 4), que
  também depende destes modelos como `Estagio[TabelaExtraida, TabelaCurada]`
- `Analysis Context` (`ColunaAnalisada`, `TabelaAnalisada`, `BancoAnalisado`,
  `ContextoDeAnalise`, métricas) — issue #8 (task 2, seção Analysis Context)

# Issue #5 — feat: tipos compartilhados e pipeline

- [x] `domain/shared/aviso.py` — `Aviso` (dataclass frozen)
- [x] `domain/shared/resultado.py` — `Sucesso[T]` / `Falha` / `Resultado[T]`
- [x] `domain/model/common/tipo_de_dado.py` — `CategoriaDeDado` (Enum) + `TipoDeDado`
  - `frozen=True` via `ConfigDict` (não estava no snippet do low_level_design.md,
    mas o texto declara "imutável após construção" — decisão de garantir isso
    em runtime, confirmada com o usuário)
- [x] `domain/model/common/metadados_de_amostra.py` — `MetadadosDeAmostra`
  - Sem validador de `tamanho_amostra <= total_linhas`: não pedido no escopo
    da issue nem no snippet do documento — mantido fiel ao design, sem
    validação extra não solicitada (avaliado adicionar durante a issue,
    revertido a pedido do usuário)
- [x] `domain/ports/estrategia_de_amostragem.py` — `EstrategiaDeAmostragem` (Protocol)
  - Decisão: adiantada desta issue (originalmente na #8) por decisão do usuário,
    pois `ConfiguracaoDeExtracao` referencia esse Protocol e não depende de
    nenhum Bounded Context — só `nome: str` + `consulta(schema, tabela) -> str`.
    Comentário adicionado na issue #8 no GitHub registrando essa decisão.
- [x] `domain/model/common/configuracao_de_extracao.py` — `ConfiguracaoDeExtracao`
      (valida `max_conexoes >= max_trabalhadores`)
  - `estrategia` sem `default_factory` (LimiteAleatorio é da issue #9 — comentário
    adicionado na issue #9 registrando o pendente)
  - Campo tipado como `InstanceOf[EstrategiaDeAmostragem]` (não
    `arbitrary_types_allowed=True` puro) — evita violar a regra do CLAUDE.md
    que restringe essa flag aos 4 modelos com `pl.DataFrame`; exigiu marcar
    `EstrategiaDeAmostragem` com `@runtime_checkable`. Validação resultante
    checa só presença de método/propriedade, não assinatura — decisão
    confirmada com o usuário após comparar alternativas (Any, arbitrary_types
    global, InstanceOf)
  - **Removido `tamanho_amostra: int = 10_000`** do snippet original do
    low_level_design.md — redundante com o parâmetro de dimensionamento que
    cada `EstrategiaDeAmostragem` concreta já carrega (`LimiteAleatorio.tamanho`),
    e não generaliza para estratégias futuras não baseadas em contagem de
    linhas (`TableSample` é percentual, `FullScan` não tem tamanho). Decisão
    confirmada com o usuário — `ConfiguracaoDeExtracao` não deve saber como
    cada estratégia dimensiona sua amostra, só orquestrar concorrência.
    `MetadadosDeAmostra.tamanho_amostra` continua existindo normalmente, como
    resultado observado pelo `Extrator`, não como parâmetro de configuração.
    Pendência de acoplamento `estrategia` ↔ dimensionamento registrada como
    comentário na issue #9
- [x] `pipeline/estagio.py` — `Estagio[Entrada, Saida]` (Protocol genérico)
- [x] `pipeline/compor.py` — `compor(*estagios)`
  - Assinatura `Estagio[T, T]` (TypeVar único), não heterogênea — único uso
    documentado é `compor(*analisadores)`, e todo Analisador é
    `Estagio[ContextoDeAnalise, ContextoDeAnalise]`. `Sobrescrita`, que é
    `Estagio[TabelaExtraida, TabelaCurada]` (heterogêneo), nunca passa por
    `compor()` — é chamada direto pelo `OrquestradorParalelo` por tabela.
    Decisão confirmada com o usuário após checar os docs
  - `Falha` ganhou campo `avisos: list[Aviso] = field(default_factory=list)`
    — o low_level_design.md dizia que `compor()` deveria retornar a `Falha`
    "com os avisos acumulados até ali", mas o tipo `Falha` original só tinha
    `erro: str`, sem onde guardar avisos. Corrigido tanto em
    `domain/shared/resultado.py` quanto no `low_level_design.md` (Resultado[T]
    e comportamento de `compor()`) — avisos emitidos antes de uma falha não
    podem ser descartados silenciosamente, pois a CLI os exibe em streaming
- [x] Testes: `tests/unit/domain/shared/`, `tests/unit/domain/model/common/`,
      `tests/unit/pipeline/` — caminho feliz, erro esperado, borda
  - Alguns testes de borda inicialmente propostos foram descartados após
    revisão (mensagem vazia em `Aviso`; `tamanho_amostra` não-numérico em
    `MetadadosDeAmostra`) — não protegiam nenhuma regra de negócio real, só
    comportamento genérico do Python/Pydantic já garantido por tipo
  - Testes usam fábricas de `Estagio[int, int]` fake em `tests/unit/pipeline/conftest.py`
    (sem depender de nenhum Analisador/Sobrescrita concreto, que ainda não existem)
- [x] `mypy --strict` + `ruff` limpos
  - `Saida` em `Estagio[Entrada, Saida]` precisou ser invariante (não
    covariante como no snippet original) porque transita por `Sucesso.valor`,
    campo de dataclass mutável — mypy rejeita covariante nesse caso
  - `Entrada` precisou ser `contravariant=True` — só aparece como parâmetro de
    `__call__`, nunca é produzido/guardado; mypy rejeita invariante num
    Protocol nesse caso ("Invariant type variable used in protocol where
    contravariant one is expected")

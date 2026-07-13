# Issue #10 — feat: SobrescritaDeTabela e OrquestradorParalelo

## Decisões tomadas na discussão prévia (antes de implementar)

> **Serialização do hash estrutural — `TipoDeDado.model_dump_json()`.** O
> `low_level_design.md` original descrevia o hash como incidindo sobre
> `col.tipo_dado` diretamente, mas isso é um `BaseModel` (frozen), não um
> primitivo hasheável. Decisão: por coluna, a tupla que entra no hash é
> `(col.nome, col.tipo_dado.model_dump_json(), col.chave_primaria,
> col.chave_estrangeira, col.tabela_referenciada, col.coluna_referenciada)`,
> concatenada com `nome_schema`/`nome_tabela` por um separador fixo, codificada
> em UTF-8, e passada para `hashlib.sha256(...).hexdigest()`. `model_dump_json()`
> serializa os campos na ordem declarada da classe — determinístico entre
> execuções, ao contrário de `repr()` (que pode mudar de forma entre versões
> do Pydantic).

> **Hash passa a incluir `tabela_referenciada`/`coluna_referenciada` — reabre
> escopo do `low_level_design.md`.** O texto original listava só `(nome,
> tipo_dado, chave_primaria, chave_estrangeira)`. Isso deixava destino de FK
> fora de detecção: se uma FK mudasse de tabela/coluna referenciada mas
> `chave_estrangeira` continuasse `True`, o hash não mudava e a curadoria
> existente permanecia aplicada sem revalidação, sem `Aviso` sobre a mudança
> de destino. Decisão: incluir os dois campos no hash, pra que mudança de
> destino de FK dispare o mesmo fluxo de "estrutura mudou" que
> adicionar/remover coluna já dispara. `docs/low_level_design.md` atualizado
> com os 6 campos.

> **Um `Aviso` por tabela no mismatch de hash, não um por categoria de
> mudança.** O "diff" de uma tabela pode ter três categorias: colunas
> adicionadas, colunas removidas, colunas com destino de FK alterado (nome
> igual, `tabela_referenciada`/`coluna_referenciada` diferentes). Decisão: um
> único `Aviso` por tabela, resumindo as três categorias com cláusulas
> omitidas quando vazias, ex.: `"Estrutura de 'public.pedidos' mudou: colunas
> adicionadas: ['desconto']; colunas com FK alterada: ['cliente_id']"` (sem
> cláusula de removidas, se nenhuma coluna foi removida).

> **`ConfiguracaoDeExtracao` perde `max_trabalhadores`/`max_conexoes` — reabre
> escopo da `#5`.** Investigação levantou que os dois campos nunca precisavam
> ser números diferentes: em `extrair_tabela`/`listar_tabelas`, cada chamada
> retém exatamente 1 conexão do pool (`getconn` no início, `putconn` no
> `finally`), não importa quantas queries rode internamente — e só o
> `OrquestradorParalelo` dispara chamadas concorrentes contra o `Extrator`.
> Logo, "quantas conexões o pool precisa" sempre foi igual a "quantos workers
> rodam ao mesmo tempo" — nunca uma distinção com diferença real, só uma
> validação (`max_conexoes >= max_trabalhadores`) garantindo uma invariante
> que nenhum código de fato explorava.
>
> Foram cogitadas (e descartadas) duas alternativas antes desta:
> 1. Expor `Extrator.paralelismo_maximo`/`max_trabalhadores` como propriedade
>    nova no Port, pro `OrquestradorParalelo` consultar — descartada por
>    misturar, no Port `Extrator` (pensado só pra "estrutura + amostra de uma
>    fonte"), uma responsabilidade de tuning de execução que não é dele, e por
>    reabrir a `#8` sem necessidade.
> 2. Manter os dois campos em `ConfiguracaoDeExtracao`, com a CLI (`#11`)
>    responsável por passar o mesmo valor pros dois lugares — descartada
>    porque exigiria que a CLI entendesse de banco de dados (quantas conexões
>    Postgres aguenta) pra configurar um wizard genérico, quebrando a meta de
>    que "a CLI só chama quem tem que chamar", sem conhecimento de fonte.
>
> **Decisão final:** `ConfiguracaoDeExtracao` fica só com
> `estrategia: EstrategiaDeAmostragem` — a única escolha genuinamente do
> usuário comum, compartilhável entre qualquer `Extrator` futuro (cada um
> traduz pro próprio dialeto, decisão já tomada na `#9`). Concorrência segura
> vira responsabilidade 100% interna e encapsulada de cada `Extrator`
> concreto — o `OrquestradorParalelo` nunca lê `ConfiguracaoDeExtracao` e
> nunca sabe quantas conexões um Postgres aguenta.

> **`ExtratorPostgres` ganha um semáforo interno em vez de expor um número —
> reabre escopo da `#9`.** Em vez de o `OrquestradorParalelo` precisar
> respeitar um limite externo, o próprio `ExtratorPostgres` nunca deixa mais
> chamadas concorrentes passarem do que seu pool aguenta: um
> `threading.Semaphore(_MAX_CONEXOES_PADRAO)` (constante interna, ex.: `8` —
> conhecimento específico de Postgres, só usado aqui dentro) é adquirido
> antes de cada `pool.getconn()` e liberado depois do `putconn()` (ou do erro
> de conexão). Se o Orquestrador disparar mais chamadas concorrentes do que
> o pool aguenta, o excesso **espera** — nunca lança exceção.
>
> Isso também mata na raiz um bug latente encontrado durante a investigação:
> `ThreadedConnectionPool.getconn()` não bloqueia quando o pool está esgotado,
> levanta `PoolError` imediatamente — exceção que `extrator_postgres.py` não
> capturava (só tratava `OperationalError`). Com o semáforo do mesmo tamanho
> do pool adquirido antes de cada `getconn()`, o pool nunca é solicitado além
> da própria capacidade — `PoolError` deixa de ser um cenário alcançável.
>
> Um parâmetro opcional `max_conexoes: int = 8` no construtor do
> `ExtratorPostgres` (fora de `ConfiguracaoDeExtracao`) permite que um usuário
> avançado ajuste esse número especificamente para esta fonte, sem vazar o
> conceito pra `ConfiguracaoDeExtracao` compartilhada nem pro
> `OrquestradorParalelo`.
>
> **`OrquestradorParalelo` volta a ser exatamente o que o `low_level_design.md`
> já especificava:** `__init__(max_trabalhadores: int = 8)`, um número
> genérico (quantas threads Python disparar), sem significado de banco,
> usado igual em `extrair` e `aplicar_sobrescritas` — sem tratamento
> diferente por fase, sem consultar nada do `Extrator` além dos dois métodos
> do Port. Zero mudança no `Extrator` Port.

> **Nota (não é pendência, só observação registrada):** `schemas: list[str]`
> em `OrquestradorDeTabelas.extrair`/`Extrator.listar_tabelas` carrega
> vocabulário de banco relacional. Um `Extrator` de arquivo ou API futuro
> (ambos já citados no `system_design_doc.md` como fontes previstas) não tem
> necessariamente "schema" no sentido SQL — embora o tipo já seja só `str`
> (identificador opaco de agrupamento), o que deixa margem pra reinterpretação
> (`"diretório"`, `"recurso"`) sem contradizer o Port. Decisão: não generalizar
> esse vocabulário agora — seria especulativo sem um segundo `Extrator` real
> pra validar contra. Revisitar quando uma issue futura (`#12`+) introduzir o
> primeiro `Extrator` não-relacional.

> **Falha de `listar_tabelas` por schema acumula, não aborta.** Mesma
> política já definida pra `extrair_tabela` por tabela: um schema com erro
> (inexistente, conexão instável) não impede que os demais schemas sejam
> listados e processados — o erro entra no mesmo resumo agregado de falhas.

> **Confirmado: qualquer falha faz a fase inteira retornar `Falha`, sem dado
> parcial.** Como `Falha` (em `Resultado`) só carrega `erro: str` e
> `avisos: list[Aviso]` — sem campo de valor parcial — uma única tabela ou
> schema com erro entre N processados descarta os resultados das demais
> chamadas que tiveram sucesso na mesma execução. O usuário precisa corrigir
> o problema e reexecutar `extrair()`/`aplicar_sobrescritas()` do zero — não
> existe retomada parcial. Como o `Extrator` só lê (nunca escreve), reexecutar
> é caro em tempo mas não é destrutivo. Retry seletivo extrapola o escopo
> desta issue — registrado como pendência pra `#11`.

> **Formato da mensagem agregada de falhas.** Definido como
> `"Falha ao {verbo} {N} de {total} {tabelas|schemas}: {schema.tabela ou
> schema}: {erro}; ..."`, itens unidos por `"; "`. Ex.:
> `Falha("Falha ao extrair 2 de 5 tabelas: public.pedidos: Não foi possível "
> "conectar: timeout; financeiro_typo: Schema 'financeiro_typo' ou tabela "
> "'?' não encontrada.")`. Mesmo padrão para `aplicar_sobrescritas`, trocando
> o verbo (`"Falha ao aplicar sobrescritas em N de M tabelas: ..."`).

> **Ordenação determinística do resultado agregado.** `ThreadPoolExecutor`
> não garante ordem de conclusão. Decisão: `list[TabelaExtraida]` (de
> `extrair`) e `BancoCurado.tabelas` (de `aplicar_sobrescritas`) são ordenados
> por `(nome_schema, nome_tabela)` antes de retornar — mesmo critério que
> `listar_tabelas` já usa (`ORDER BY table_name`). O paralelismo real da
> execução não muda, só a agregação final vira determinística.

## Escopo desta issue

- [x] `domain/model/common/configuracao_de_extracao.py` — remove
      `max_trabalhadores`/`max_conexoes` e `_valida_max_conexoes`; fica só
      `estrategia: EstrategiaDeAmostragem` (reabre escopo da `#5`)
- [x] `infrastructure/adapters/extractors/postgres/extrator_postgres.py` —
      adiciona `max_conexoes: int = 8` no construtor (fora de
      `ConfiguracaoDeExtracao`), `threading.Semaphore(max_conexoes)` adquirido
      antes de cada `getconn()` e liberado após `putconn()`/erro de conexão
      (reabre escopo da `#9`)
- [x] `infrastructure/adapters/overrides/sobrescrita_de_tabela.py` —
      `SobrescritaDeTabela(Estagio[TabelaExtraida, TabelaCurada])`:
  - Hash SHA-256 sobre `(nome_schema, nome_tabela, [(col.nome,
    col.tipo_dado.model_dump_json(), col.chave_primaria,
    col.chave_estrangeira, col.tabela_referenciada, col.coluna_referenciada)
    for col in colunas])`
  - `_traduzir`: mapeamento estrutural `ColunaExtraida`/`TabelaExtraida` →
    `ColunaCurada`/`TabelaCurada` sem curadoria (campos vazios)
  - `_aplicar_overrides`: lê `diretorio_sobrescritas/<schema>/<tabela>.yaml`;
    hash bate → aplica curadoria; hash não bate → atualiza skeleton
    preservando curadoria de colunas remanescentes + `Aviso` único por
    tabela (cláusulas adicionadas/removidas, omitindo vazias; se os nomes
    de coluna não mudaram, mensagem genérica de "estrutura mudou" — hash é
    só de tabela, não por coluna, então não aponta qual coluna mudou; hash
    por coluna registrado como possível melhoria futura, não implementado);
    arquivo não existe → gera skeleton + `Aviso` de criação
  - YAML malformado → `Falha("Sobrescrita de '<schema>.<tabela>' está "
    "malformada: <detalhe>")`
- [x] `infrastructure/adapters/orchestrator/orquestrador_paralelo.py` —
      `OrquestradorParalelo(OrquestradorDeTabelas)`:
  - `__init__(max_trabalhadores: int = 8)`
  - `extrair`: `ThreadPoolExecutor(max_trabalhadores)`; lista tabelas por
    schema (falha de listagem acumula, não aborta); acumula falhas de
    `extrair_tabela`; `Falha` agregada se qualquer schema/tabela falhou;
    senão `list[TabelaExtraida]` ordenado por `(nome_schema, nome_tabela)`
  - `aplicar_sobrescritas`: mesma política de acumulação/agregação sobre
    `sobrescrita(tabela)`; agrega em `BancoCurado` ordenado
- [x] `docs/low_level_design.md` — atualiza `ConfiguracaoDeExtracao`
      (só `estrategia`), `ExtratorPostgres` (semáforo interno, `max_conexoes`
      no construtor), hash da `SobrescritaDeTabela` (6 campos) e
      `OrquestradorParalelo` (mensagem agregada, ordenação)

## Testes

### `tests/unit/domain/model/common/test_configuracao_de_extracao.py` (extensão)

- [x] Remove testes de `max_trabalhadores`/`max_conexoes`/validação cruzada;
      mantém só caminho feliz (`estrategia` aceita) e erro (tipo inválido)

### `tests/unit/infrastructure/adapters/extractors/postgres/test_extrator_postgres.py` (extensão)

- [x] Caminho feliz: `max_conexoes` default (`8`) dimensiona pool e semáforo
- [x] Borda: `N+1` chamadas concorrentes com `max_conexoes=N` — a `N+1`-ésima
      espera (não levanta `PoolError`) até uma conexão ser liberada

### `tests/unit/infrastructure/adapters/overrides/` (com `conftest.py`)

- [x] `SobrescritaDeTabela`: caminho feliz (hash bate, aplica curadoria
      existente do YAML)
- [x] Erro esperado: YAML malformado → `Falha` com mensagem clara
- [x] Borda: arquivo não existe (1ª execução) → gera skeleton + `Aviso` de
      criação
- [x] Borda: hash não bate por coluna adicionada → atualiza skeleton
      preservando curadoria remanescente + `Aviso` com cláusula "adicionadas"
- [x] Borda: hash não bate sem mudança de nomes (tipo alterado) → `Aviso`
      com mensagem genérica de "estrutura mudou"

### `tests/unit/infrastructure/adapters/orchestrator/` (com `conftest.py`)

- [x] `OrquestradorParalelo`: caminho feliz — `extrair`/`aplicar_sobrescritas`
      em paralelo, resultado ordenado por `(nome_schema, nome_tabela)`
- [x] Erro esperado: uma tabela (ou um schema, em `extrair`) falha entre
      várias → `Falha` agregada no formato definido, nenhum resultado
      parcial retornado, demais chamadas não interrompidas
- [x] Borda: lista de schemas/tabelas vazia → `Sucesso` com lista/`BancoCurado`
      vazios

## Pendências para próximas issues (não resolvidas aqui)

- **Retry seletivo na CLI (`#11`)**: como qualquer falha descarta os
  resultados parciais desta execução, um comando `--apenas-falhas` (ou
  equivalente) que reexecute só os schemas/tabelas que falharam evitaria
  reprocessar tudo em bancos grandes. Depende do wizard da CLI (`#11`)
  existir primeiro.
- **Vocabulário `schemas`/`schema` genérico demais para SQL (`#12`+)**: quando
  o primeiro `Extrator` não-relacional (arquivo/API) for planejado, revisitar
  se `schema: str` continua fazendo sentido como nome, ou se merece um termo
  mais neutro (`namespace`, `origem`). Não é bloqueante — o tipo já é opaco
  o bastante pra não impedir uma implementação não-relacional agora.

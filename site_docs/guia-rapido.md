# Guia rápido

Este guia roda o wizard de ponta a ponta contra um Postgres de exemplo, com dois schemas
fictícios de uma loja (`public.clientes` e `public.pedidos`). Os comandos e telas abaixo
são os reais do `ddf`; só os valores digitados (host, nomes de tabela) são de exemplo.

## Antes de começar

Você precisa de um Postgres ou MariaDB acessível, com host, porta, banco/usuário e senha
em mãos. Se ainda não instalou o `ddf`, veja [Instalação](instalacao.md) primeiro.

## Rodar o wizard

```bash
ddf
```

O wizard imprime um banner e conduz o resto da execução por prompts interativos. Nada
acontece no banco antes da etapa de extração: as primeiras perguntas só coletam decisões.

## 1. Fonte e conexão

```
? Qual fonte? (setas para navegar, enter confirma)
❯ PostgreSQL
  MariaDB
```

Em seguida, host, porta, banco, usuário e senha:

```
? Host do Postgres: localhost
? Porta: 5432
? Banco de dados: loja
? Usuário: analista
? Senha: ********
? Parâmetros extra de conexão (opcional, ex.: sslmode=require):
```

O `ddf` testa a conexão antes de seguir e resume as decisões:

```
✓ Conexão validada.

├─ Fonte PostgreSQL
├─ Host localhost
├─ Porta 5432
├─ Banco loja
├─ Usuário analista
└─ Senha ****
```

Se a conexão falhar, o wizard pergunta se você quer tentar de novo (até 3 tentativas)
antes de encerrar.

## 2. Escopos e tabelas

```
? Escolha um ou mais escopos: (digite para filtrar, espaço marca, enter confirma)
❯◉ public
```

Por padrão o `ddf` extrai todas as tabelas do escopo escolhido. Para restringir a um
subconjunto:

```
? Restringir tabelas extraídas? (y/N) y
? Escolha uma ou mais tabelas:
❯ ◉ public › clientes
  ◉ public › pedidos
```

## 3. Estratégia de amostragem

```
? Qual estratégia de amostragem?
❯ Percentual de linhas
  Tabela inteira
  Amostragem por faixa
```

Cada estratégia pede seus próprios parâmetros. "Percentual de linhas" pergunta o
percentual a amostrar e, opcionalmente, um seed para reprodutibilidade:

```
? Percentual de amostragem (0-100): 20
? Seed para reprodutibilidade (opcional, deixe em branco para usar o padrão fixo do ddf):
```

O que cada estratégia garante (e os trade-offs entre elas) está em
[Estratégias de amostragem](guia/amostragem.md).

## 4. Extração

Sem decisão nova: o `ddf` lê as tabelas escolhidas em paralelo e mostra uma barra de
progresso.

```
⠋ Tabelas extraídas (2/2)

▮▮▮▮▮▮▮▮▮▮▮▮

✓ 2 tabela(s) extraída(s).
duração: 3s
```

## 5. Curadoria

O `ddf` pergunta onde gravar os overrides:

```
? Diretório de overrides: overrides
```

Um YAML skeleton é criado por tabela (`overrides/public/clientes.yaml`,
`overrides/public/pedidos.yaml`) e o wizard pausa:

```
✓ 2 skeleton(s) criado(s)/atualizado(s), 0 preservado(s) sem mudança. Preencha a
curadoria e reexecute.

Edite os YAMLs de overrides em '/caminho/absoluto/overrides' e aperte uma tecla
para continuar...
```

Um skeleton recém-gerado tem `papel_de_negocio` e `regras_de_negocio` em branco, prontos
para preencher:

```yaml
hash: 3f1a9c...
papel_de_negocio: ""
regras_de_negocio: []
colunas:
  id:
    papel_de_negocio: ""
    regras_de_negocio: []
  email:
    papel_de_negocio: ""
    regras_de_negocio: []
```

Com o editor aberto numa janela paralela, um preenchimento mínimo já é suficiente:

```yaml
hash: 3f1a9c...
papel_de_negocio: "Cadastro de clientes da loja"
regras_de_negocio: []
colunas:
  id:
    papel_de_negocio: "Identificador único do cliente"
    regras_de_negocio: []
  email:
    papel_de_negocio: "E-mail de contato, único por cliente"
    regras_de_negocio:
      - "Formato de e-mail válido"
```

Ao apertar uma tecla, o `ddf` reaplica os overrides já editados:

```
✓ 2 tabela(s) curada(s).
duração: 1s
```

Formato completo do override e o que acontece quando a estrutura da fonte muda entre
execuções: [Curadoria (overrides)](guia/curadoria.md).

## 6. Artefatos

```
? Escolha um ou mais geradores: (digite para filtrar, espaço marca, enter confirma)
❯ ◉ Markdown
  ◉ Dbt
  ◯ ContextoDeIA
```

O que cada um gera está detalhado em [Artefatos gerados](index.md#artefatos).

## 7. Análise

Sem decisão nova: o `ddf` calcula as métricas sobre os dados curados.

```
▮▮▮ ▄ █ ▄ ▮▮▮ Analisando...

✓ Análise concluída.
duração: 2s
```

Avisos de análise (quando existem) aparecem aqui, antes da confirmação final. O que cada
métrica significa está em [Analisadores (métricas)](guia/analisadores.md).

## 8. Confirmação

```
? Diretório de destino dos artefatos: artefatos
? Gerar Markdown, Dbt em subpastas dentro de '/caminho/absoluto/artefatos'? (Y/n) y
```

Ao confirmar, cada gerador escolhido escreve na sua própria subpasta:

```
✓ 'Markdown': artefato escrito em '/caminho/absoluto/artefatos/markdown'.
✓ 'Dbt': artefato escrito em '/caminho/absoluto/artefatos/dbt'.
```

Por fim, o wizard pergunta se você quer repetir o processo (útil para reconectar a outra
fonte ou testar outra combinação de artefatos) sem reiniciar o comando:

```
? Executar novamente? (y/N)
```

## Estrutura final em disco

Depois dessa execução, o diretório de trabalho tem:

```
.
├── ddf.log
├── overrides/
│   └── public/
│       ├── clientes.yaml
│       └── pedidos.yaml
└── artefatos/
    ├── markdown/
    └── dbt/
```

`ddf.log` registra o que aconteceu internamente durante a execução (nunca é impresso no
terminal). `overrides/` é o que você versiona como curadoria: reexecutar o wizard contra a
mesma fonte, sem mudança estrutural, preserva esse conteúdo. `artefatos/` é o resultado
final, uma subpasta por gerador escolhido.

## Próximos passos

- [Extração](guia/extracao.md), [Curadoria](guia/curadoria.md), [Estratégias de
  amostragem](guia/amostragem.md) e [Analisadores](guia/analisadores.md): cada etapa em
  detalhe.
- [Artefatos](index.md#artefatos): formato de cada artefato.
- [Extensão via plugins](extensao.md): registrar um Extrator ou Gerador próprio.

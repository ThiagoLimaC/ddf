# Gitflow — ddf

## Modelo de branches

| Branch | Papel | Merge recebido |
|---|---|---|
| `main` | Código estável / releases | Squash merge de `develop` |
| `develop` | Integração contínua das features | Merge commit de features |
| `tipo/<issue-id>-descricao` | Feature/fix em desenvolvimento | — |

`main` e `develop` são branches permanentes. Nunca se faz commit direto nelas.

## Tipos de branch

| Prefixo | Quando usar |
|---|---|
| `feat/` | Nova funcionalidade |
| `fix/` | Correção de bug |
| `docs/` | Documentação apenas |
| `refactor/` | Refatoração sem mudança de comportamento |
| `test/` | Adição ou correção de testes |
| `chore/` | Setup, CI, dependências |

Exemplos:
```
feat/3-extrator-postgres
fix/15-hash-estrutural-fk
docs/1-plano-e-documentacao
```

## Fluxo de trabalho

```
develop ──────────────────────────────────► develop
           │                        ▲
           └── feat/12-extrator ────┘
                (commits normais)    (merge commit)

develop ──────────────────────────────────► main
                                    (squash merge)
```

1. Branch de `develop`: `git checkout -b feat/12-extrator-postgres develop`
2. Commits na branch seguindo Conventional Commits
3. PR aberto para `develop`
4. Critérios de merge satisfeitos → merge commit para `develop`
5. Quando `develop` está estável → PR para `main` com squash merge

## Commits — Conventional Commits

Formato obrigatório para todos os commits (dentro de features e squash de release):

```
tipo(escopo): descrição curta em português (#issue)

corpo opcional explicando o porquê
```

| Tipo | Quando usar |
|---|---|
| `feat` | Nova funcionalidade |
| `fix` | Correção de bug |
| `docs` | Documentação |
| `refactor` | Refatoração |
| `test` | Testes |
| `chore` | Setup, CI, dependências |
| `perf` | Melhoria de performance |

Exemplos:
```
feat(extrator): adiciona ExtratorPostgres com ThreadedConnectionPool (#12)
fix(sobrescrita): corrige hash estrutural para colunas com FK (#15)
test(analisador): adiciona caso de borda para amostra vazia (#18)
```

## Padrão de Pull Request

### Título do PR

Seguir Conventional Commits — o título do PR se torna a mensagem do squash commit,
então o formato precisa ser consistente:

```
tipo(escopo): descrição curta em português (#issue)
```

Exemplos:
```
feat(extrator): adiciona ExtratorPostgres com ThreadedConnectionPool (#3)
docs(projeto): adiciona documentação base e padrões de desenvolvimento (#1)
fix(sobrescrita): corrige hash estrutural para colunas com FK (#15)
```

### Estratégia de merge

| Origem | Destino | Estratégia |
|---|---|---|
| `feat/*`, `fix/*`, `docs/*`, etc. | `develop` | **Merge commit** — preserva todos os commits da feature |
| `develop` | `main` | **Squash merge** — um commit por entrega, histórico limpo |

### Template obrigatório

```markdown
## O que foi feito

<!-- Descrição narrativa da mudança -->

## Checklist de testes

- [ ] Caminho feliz coberto
- [ ] Erro esperado coberto
- [ ] Caso de borda coberto
- [ ] `mypy --strict` passa localmente
- [ ] `ruff` passa localmente

## Breaking changes

<!-- Se não houver, escreva "Nenhum" -->
```

### Critérios de merge

Todos os itens abaixo devem estar satisfeitos:

- [ ] CI verde (ruff + mypy --strict + pytest)
- [ ] Branch atualizada com `develop` (sem conflitos)
- [ ] Review aprovado
- [ ] Template do PR preenchido

### Mensagem do squash commit (develop → main)

Usar Conventional Commits com referência à issue principal da entrega:

```
feat(pipeline): adiciona modelo de domínio completo com Bounded Contexts (#2)
```

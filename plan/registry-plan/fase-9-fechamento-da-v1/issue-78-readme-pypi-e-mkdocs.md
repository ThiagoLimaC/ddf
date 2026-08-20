# Issue #78 — docs: README real de publicação no PyPI e documentação mkdocs

## Contexto

`README.md` hoje tem 5 bytes (`# ddf`). Não existe `mkdocs.yml` nem
dependência de `mkdocs`/`mkdocs-material` no repo. `pyproject.toml` não tem
`license`/`license-files` nem `[project.urls]` — faltam para publicação real
no PyPI (hoje só TestPyPI). O `docs/` atual (`prd.md`,
`system_design_doc.md`, `low_level_design.md`, `engineer_guidelines.md`,
`gitflow.md`) é documentação **interna** de engenharia — fonte de verdade
para o conteúdo público, não o conteúdo em si.

**Achado durante o planejamento, antes de qualquer conteúdo:** o nome do
pacote `ddf` já está registrado por outro projeto no PyPI real (confirmado —
`pypi.org/pypi/ddf/json` responde 200, versão `0.0.0` publicada por
terceiro). O comando local (`[project.scripts] ddf = "ddf:main"`) continua
`ddf` independente disso, mas `pip install ddf` pode não ser o comando final
de instalação — nome de publicação é decisão em aberto (ver "Perguntas em
aberto").

## Decisões já tomadas com o usuário

- **Caráter do projeto:** o `ddf` fica exposto como peça de portfólio no
  GitHub do usuário — a documentação pública precisa comunicar bagagem
  técnica real (arquitetura hexagonal + DDD por Bounded Contexts, decisões
  de engenharia não óbvias), não só instruções de uso.
- **Escopo do site mkdocs:** usuário final (instalação, uso do wizard,
  artefatos gerados, extensão via entry points `ddf.extratores`/
  `ddf.geradores`) **+** seção "como funciona por dentro" resumindo a
  arquitetura — resumo, não cópia de `system_design_doc.md`/
  `low_level_design.md`, que continuam sendo os documentos internos
  completos.
- **Tema:** `mkdocs-material`, sem etapa de comparação — padrão já usado por
  dbt docs, FastAPI, Pydantic, Polars. Deploy via GitHub Actions a cada push
  na main, publicado no GitHub Pages.
- **Escopo desta issue:** os três itens do corpo original juntos — README,
  metadados de `pyproject.toml` (`license`, `[project.urls]`), e o site
  mkdocs — compartilham as mesmas decisões de estrutura/conteúdo.
- **Agente novo, não versionado:** `especialista-documentacao-framework`
  (`.claude/agents/`, fora do controle de versão, mesmo padrão de
  `especialista-ux-terminal`) — só pesquisa e propõe (`Read`/`Grep`/`Glob`/
  `Bash`/`WebSearch`/`WebFetch`, sem `Edit`/`Write`). Interroga o usuário
  quando uma decisão de conteúdo não for óbvia. Sinaliza para o Arquiteto de
  Software (dúvida de arquitetura/Ports/Bounded Contexts) ou Engenheiro de
  Dados (dúvida de amostragem/métricas/comportamento de motor de banco) em
  vez de resolver de memória qualquer afirmação técnica que vá virar texto
  público.

## Perguntas em aberto — resolvidas

- [x] **Nome de publicação no PyPI: `ddf-framework`.** Confirmado livre
      (`pypi.org/pypi/ddf-framework/json` responde 404). `[project.name]`
      muda de `ddf` para `ddf-framework` em `pyproject.toml`; `[project.
      scripts]` continua expondo o comando `ddf` (`ddf = "ddf:main"`) —
      nome de distribuição PyPI e nome de comando local são independentes,
      só o primeiro precisava mudar.
- [x] **Licença: MIT.** Adicionar `LICENSE` (texto padrão MIT, copyright
      ThiagoLimaC) + `license = "MIT"` em `pyproject.toml`.
- [x] **Domínio do GitHub Pages: padrão.** Remote confirmado
      (`git@github.com:ThiagoLimaC/ddf.git`) → site publicado em
      `https://thiagolimac.github.io/ddf/`. Sem CNAME customizado.

## Fluxo de trabalho

1. **Pesquisa e proposta** (`especialista-documentacao-framework`, avulso) —
   traz estrutura de navegação do mkdocs, conteúdo proposto do README, prior
   art citado, e as perguntas em aberto acima resolvidas ou explicitamente
   levantadas para decisão do usuário.
2. **Revisão do usuário** — aprova/ajusta estrutura antes de qualquer
   arquivo ser escrito.
3. **Sinalização técnica, se necessária** — qualquer afirmação técnica sobre
   arquitetura (Arquiteto de Software) ou dados/amostragem (Engenheiro de
   Dados) que o especialista não tiver certeza vira pergunta explícita antes
   de virar texto público.
4. **Implementação** — depois da aprovação, escrita real dos arquivos
   (README, `pyproject.toml`, `mkdocs.yml`, páginas do site, workflow do
   GitHub Actions), seguindo a etapa de explicação por arquivo do
   `docs/engineer_guidelines.md`.

## Escopo desta issue

- [x] Resolver as 3 perguntas em aberto (nome PyPI, licença, domínio Pages)
- [x] `pyproject.toml` — `name = "ddf-framework"`, `license = "MIT"`,
      `license-files`, `[project.urls]`, `[tool.uv.build-backend]
      module-name = "ddf"` (necessário para o wheel continuar expondo o
      módulo `ddf`, não `ddf_framework`, com a mudança de nome), grupo
      `[dependency-groups] docs` com `mkdocs-material`. Validado gerando o
      wheel de verdade (`uv build --wheel`) e inspecionando o `.whl`.
- [x] `LICENSE` (arquivo novo na raiz, MIT, texto padrão em inglês —
      mantido sem tradução para preservar reconhecimento automático do
      GitHub/PyPI)
- [x] `README.md` — tagline, descrição (hexagonal **escopado**, não a
      receita completa), instalação (`pip install ddf-framework`),
      quickstart do comando `ddf`, o que o framework gera, seção
      Arquitetura (árvore de diretórios enxuta + diagrama mermaid do
      pipeline + disciplina de testes sem números fabricados), badges,
      licença MIT, link para o site mkdocs, placeholder comentado para GIF
      de demo
- [x] `mkdocs.yml` (novo) + `docs_dir: site_docs/`
- [ ] Estrutura de páginas do site (instalação/uso/extensão + "Arquitetura"
      — nome final, "como funciona por dentro" descartado por informal),
      conteúdo escrito por seção após aprovação do esqueleto.
      **Início (`index.md`): feito** — extração, curadoria, análise,
      artefatos gerados, "como funciona" com árvore de decisões do wizard
      em bloco colapsável. **Instalação e Guia rápido: feitos** — Guia
      rápido roda o wizard de ponta a ponta com exemplo real (2 tabelas
      fictícias), prompt por prompt copiado do código, estrutura final em
      disco. **Guia do usuário: feito** (4 páginas — sem `avisos.md`
      dedicado, decisão do usuário: cada página carrega sua própria seção
      "Avisos" quando aplicável). **Artefatos gerados: feito** (visão geral
      + dbt + markdown + contexto-ia, cada uma com a regra exata por trás
      de cada campo/teste gerado a partir de métrica real). **Arquitetura:
      feito** (7 páginas: índice, portas e adaptadores, métricas como Value
      Objects, hash estrutural da Sobrescrita, pipeline e paralelismo,
      tecnologias, testes e qualidade). **Extensão via plugins: feito**
      (inclui os 3 achados honestos da banca técnica abaixo). **Notas da
      versão: feito** (primeira entrada da v1, limitações em admonition
      abaixo do texto corrido). Todas as páginas do site estão escritas;
      falta só o workflow de deploy e a validação final.
      **Pendência pra página Arquitetura:** os 5 critérios exatos de
      `_elegivel_para_enumeracao` (categoria excluída, piso de 100 linhas,
      cardinalidade < 10, `percentual_unico` < 10%, cobertura top-10 >= 90%)
      foram levantados durante `artefatos/dbt.md`, mas o usuário decidiu
      detalhar isso na Arquitetura em vez de na página de artefato — não
      perder esse levantamento quando chegar a hora.
- [x] **Novo, decisão desta rodada:** diagrama de arquitetura hexagonal
      estilo "Domain → Ports → Adapters" (hexágonos concêntricos, Ports
      irradiando para Adapters externos) adaptado ao `ddf` — reservado para
      as páginas "Arquitetura"/"Extensão via plugins" do **site**, não para
      o README (README fica só com o fluxograma linear do pipeline, mais
      enxuto). Reforça a analogia de "peça de Lego" já planejada para
      "Extensão via plugins": Domain = os 3 Bounded Contexts; anel de Ports
      = Extrator/Analisador/Gerador/OrquestradorDeTabelas/
      EstrategiaDeAmostragem; Adapters externos = `ExtratorPostgres`/
      `ExtratorMariaDB`/`GeradorMarkdown`/`GeradorDbt`/
      `GeradorContextoDeIA` + plugins de terceiro (visualmente destacados
      como a mesma "peça" encaixando sem alterar o hexágono central).
      Mermaid não desenha hexágonos concêntricos nativamente — avaliar na
      etapa de execução se aproxima via subgraphs em camadas (Domain →
      Ports → Adapters) ou se vale a pena uma imagem estática.
- [ ] Workflow de GitHub Actions — build + deploy do mkdocs no GitHub Pages
      a cada push na `main` (gatilho confirmado: push, não pull_request —
      reflete o squash merge já aprovado)
- [ ] Validação: `mkdocs build --strict` sem warning, site navegável local
      (`mkdocs serve`) antes do primeiro deploy real

## Pendência registrada — issue #154

`site_docs/arquitetura/` publica o diagrama hexagonal Domain → Ports →
Adapters (item "Novo, decisão desta rodada" acima). A issue #154
(`refactor(cli): torna a CLI adapter fino — orquestração move para
pipeline/, simetria total`) move o núcleo de `cli/etapas/*.py` para um
módulo `pipeline/` novo, que passa a ser o único ponto de chamada às Ports
a partir da CLI (a CLI deixa de chamar qualquer Port diretamente). Quando a
#154 fechar, revisar e atualizar:

- [x] Diagrama hexagonal em `site_docs/arquitetura/` — acrescentada a
      camada `pipeline/` (subgraphs `etapas/*`/`comum/`) entre o adapter
      inbound (CLI) e o anel de Ports, no diagrama "Domain, Ports e
      Adapters" de `portas-e-adaptadores.md`.
- [x] Texto de `site_docs/arquitetura/` — nova seção "CLI: adapter fino,
      `pipeline/` como fronteira única até as Ports" em
      `portas-e-adaptadores.md` (extração total, por que `pipeline/comum/`
      não virou Port); `testes-e-qualidade.md` corrigido (CLI fakeia
      `pipeline.etapas.*`, não a Port diretamente); `pipeline-e-paralelismo.md`
      passou a citar `pipeline/comum/` vs `pipeline/etapas/`; `index.md`
      atualizado na lista "Continue por aqui". Validado com
      `mkdocs build --strict` limpo.
- [x] Conferido `site_docs/extensao.md` — cita só `extractors/comum/`
      (cauda do path, sem `adapters/outbounds/` na frente), nenhuma
      referência a `cli/etapas/`; nada a corrigir aqui.

## Verificação final

- [ ] `mkdocs build --strict` limpo
- [ ] Link do README para o site publicado funciona (após primeiro deploy)
- [ ] `pip install -e .` / `uv build` continuam funcionando após mudanças em
      `pyproject.toml`
- [ ] Nenhuma afirmação técnica da seção "como funciona por dentro" ficou
      sem confirmação do Arquiteto de Software/Engenheiro de Dados quando
      havia dúvida genuína

# Issue #132 — restringe a extração a tabelas específicas dentro do escopo

## Contexto

Etapa "Escolher escopos" do wizard só permitia escopos inteiros
(schema/database); a extração sempre pegava todas as tabelas dos escopos
escolhidos (`OrquestradorParalelo.extrair` listava `extrator.listar_tabelas
(escopo)` internamente para cada escopo). Quem queria só 3 tabelas de um
schema com 120 era obrigado a extrair tudo.

## Banca de revisão do plano (antes da implementação)

Arquiteto de Software + Engenheiro de Dados + PO + especialista-ux-terminal
revisaram o rascunho de plano antes do código — mudança de contrato de Port
(`OrquestradorDeTabelas.extrair`), mesmo critério já usado para #44/#89/#95/
#105. Todos aprovaram com ressalvas, sem bloqueio. Achados incorporados:

- **Arquiteto:** mudança `escopos: list[str]` → `pares: list[tuple[str,
  str]]` em `OrquestradorDeTabelas.extrair` é separação de responsabilidade
  genuína (descobrir pares vs. coordenar extração paralela), não indireção
  decorativa — único caller real é `wizard.py`, sem consumidor externo, sem
  vazamento de Bounded Context. `ao_conhecer_total` removido como
  consequência direta (deixa de fazer sentido com listagem única, feita
  antes, pelo chamador).
- **Engenheiro de dados:** mover `listar_tabelas` para antes (CLI) é neutro
  em custo — mesma conexão pooled, mesma query de catálogo, sem round-trip
  extra. Recomendação incorporada: cobrir em teste de integração o caso de
  FK (simples e composta) apontando para tabela do mesmo escopo
  deliberadamente não selecionada — a issue torna esse caminho, já tratado
  por `_avisos_de_fk_composta_sem_chave_candidata` e pela omissão de
  `relationships` no `GeradorDbt`, muito mais frequente em uso real.
- **PO:** escopo bate com a issue; pediu que a remoção de `ao_conhecer_total`
  apareça explícita no commit/PR como reabertura de escopo (mesmo padrão de
  #77/#93/#95), não como efeito colateral silencioso — feito abaixo.
- **Especialista UX terminal:** consultado pela própria issue. Recomendou
  checkbox vazio (não pré-marcado) em vez de "todas pré-marcadas" — reforçado
  pelo usuário diretamente durante o planejamento: pergunta binária logo
  após escolher escopo(s) ("extração completa do escopo" vs. "escolher
  tabelas específicas"), só quem escolhe a segunda opção vê a lista.
  Recomendou também manter a nova etapa sob o cabeçalho existente "Escolher
  escopos" (sem bump de `_TOTAL_ETAPAS`, que continua 11) — precedente:
  `conectar()` já agrupa várias perguntas novas (fonte/host/porta/usuário/
  senha) sob um único cabeçalho, porque são a mesma decisão sendo
  detalhada, não fases distintas do pipeline.

Plano completo da rodada de revisão arquivado em
`/home/dev/.claude/plans/merry-marinating-stearns.md` (fora do repositório,
não versionado).

## Decisões de desenho fechadas

- [ ] `OrquestradorDeTabelas.extrair`: `escopos: list[str]` → `pares:
      list[tuple[str, str]]`; `ao_conhecer_total` removido.
      `OrquestradorParalelo.extrair` para de listar internamente.
- [ ] `cli/etapas/extracao.py`: `listar_pares(extrator, escopos)` (agrega
      com sucesso parcial, mesma semântica que saía do Orquestrador) +
      `escolher_tabelas(pares_disponiveis)` (pergunta binária "extração
      completa do escopo" vs. "escolher tabelas específicas"; checkbox
      vazio + loop até marcar ao menos uma). `extrair` passa a receber
      `pares` e usa `progresso_paralelo(total=len(pares))` direto.
- [ ] `prompts.escolher_multiplos` ganha `permite_vazio: bool = False` —
      só quando `True` uma submissão vazia (não cancelamento) devolve `[]`
      em vez de `sys.exit(0)`; todos os demais call sites inalterados.
- [ ] `wizard.py`: nova etapa sob o cabeçalho "Escolher escopos" (checkpoint
      2), sem novo `cabecalho_etapa`, `_TOTAL_ETAPAS` continua 11.
      `_sair_se_vazio` (já existente) reusado se a listagem falhar para
      todos os escopos.
- [ ] Docs: `system_design_doc.md` (prosa "14 etapas" → "15 etapas", nº de
      checkpoints do wizard não muda), `low_level_design.md` (assinatura do
      Port + lista numerada de etapas), `plan/tasks.md` (reabertura de
      escopo na Task 7, mencionando explicitamente a remoção de
      `ao_conhecer_total`).
- [ ] Testes: `test_orquestrador_paralelo.py` (pares em vez de escopos, sem
      `ao_conhecer_total`), `test_extracao.py` (`listar_pares`/
      `escolher_tabelas`, feliz/borda/default), `test_prompts.py`
      (`permite_vazio`), `test_wizard_end_to_end.py` (nova pergunta no
      fluxo), integração nova de FK apontando para tabela excluída da
      seleção.

## Fora de escopo (registrado, não implementado nesta issue)

- Sinalizar no checkbox de seleção quando uma tabela é referenciada por FK
  de outra já marcada/desmarcada (sugestão do engenheiro-de-dados) — o
  Aviso pós-extração já cobre o caso.

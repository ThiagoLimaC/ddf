# Hash estrutural

A [Curadoria](../guia/curadoria.md) já documenta o que acontece do ponto de vista de quem
usa o `ddf`: um hash decide se a estrutura de uma tabela mudou desde a última execução, e
o override é preservado ou atualizado a partir disso. Esta página cobre o porquê da
implementação por trás desse comportamento: a função `_calcular_hash_estrutural`, dentro
da `SobrescritaDeTabela`, a Anti-Corruption Layer entre Extraction e Curation.

## O que entra no hash

O hash é um SHA-256 sobre uma lista ordenada de partes, concatenadas com um separador antes
de serem codificadas:

1. Nome do escopo e nome da tabela.
2. Para cada coluna, na ordem em que aparece em `tabela.colunas`: nome, o tipo de dado
   serializado como JSON, se é chave primária, se é chave estrangeira, se aceita nulo, se é
   única, e as referências de chave estrangeira (também serializadas).
3. Cada restrição `UNIQUE` composta da tabela.
4. Cada restrição de chave estrangeira composta da tabela.

Qualquer diferença em qualquer um desses campos, em qualquer coluna, produz um hash
diferente do gravado no override.

## Limitação conhecida: sensibilidade à ordem das colunas

A lista de colunas é percorrida na ordem em que `tabela.colunas` as apresenta, não ordenada
por nome nem tratada como um conjunto. Isso tem uma consequência observável: reordenar
colunas na fonte, sem adicionar, remover ou alterar nenhuma, muda o hash, porque a posição
de cada coluna na lista afeta a posição das suas partes na string concatenada antes do
SHA-256.

Isso não é uma escolha de design registrada em lugar nenhum. `docs/low_level_design.md`
documenta minuciosamente cada campo que entra no hash, cada um ligado à issue e ao caso
real que motivou sua inclusão, até uma melhoria descartada (hash por coluna, avaliado e
adiado na issue #10, por falta de caso de uso concreto pedindo essa precisão). A
sensibilidade a reordenação está ausente desse histórico inteiro: é efeito colateral da
implementação mais direta (percorrer a lista na ordem em que ela vem), não um trade-off
avaliado e aceito.

O impacto real é ruído, não perda de dado. A curadoria no skeleton YAML é chaveada por
nome de coluna (um `dict`, não uma lista), então uma reordenação pura nunca descarta
curadoria já feita. O que ela dispara é uma reavaliação desnecessária do skeleton: o hash
diverge, o arquivo é reescrito, e o `Aviso` genérico ("estrutura mudou, nomes preservados")
é emitido mesmo sem nenhuma mudança semântica na tabela, um alarme falso e um diff espúrio
no skeleton versionado.

## Por que hash sobre serialização, não comparação direta dos objetos Pydantic

O override em disco guarda só o hash (`hash: str`, um campo do YAML), não uma cópia
serializada da `TabelaExtraida` inteira da execução anterior. Comparar objetos Pydantic
diretamente exigiria persistir e recarregar a estrutura completa da execução anterior a
cada reexecução, um artefato maior e mais frágil a mudanças na própria definição dos
modelos (campo novo em `ColunaExtraida`, por exemplo, quebraria a comparação de um objeto
salvo por uma versão anterior do `ddf`). Um hash de string:

- É uma única linha no YAML, fácil de revisar em um diff de Git: a mudança de hash em si
  já sinaliza "algo estrutural mudou aqui", mesmo antes de ler a mensagem do `Aviso`.
- Não depende de manter compatibilidade de desserialização entre versões do `ddf`, só
  de recalcular o hash da estrutura atual e comparar duas strings.
- É barato de calcular e comparar a cada execução, mesmo em um lote com centenas de
  tabelas.

## Onde isso se encaixa na responsabilidade única da ACL

A `SobrescritaDeTabela` tem uma responsabilidade: produzir `TabelaCurada` a partir de
`TabelaExtraida`. Ela cumpre essa responsabilidade em duas fases internas com razões de
mudança diferentes: `_traduzir` (mapeamento estrutural `ColunaExtraida` → `ColunaCurada`,
que muda quando a estrutura da fonte muda) e `_aplicar_overrides` (aplica a curadoria do
YAML, que muda quando as regras de curadoria mudam).

O cálculo do hash não é uma terceira fase dessas duas: é o que decide, antes delas
rodarem, qual caminho a chamada vai seguir. Sem override em disco, gera o skeleton. Com
override e hash batendo, aplica a curadoria existente sobre a tradução, sem reescrever
nada. Com override e hash divergente, atualiza o skeleton preservando a curadoria das
colunas que sobreviveram, e emite um `Aviso` explicando o que mudou.

## O que o diff realmente distingue

A comparação de hash é binária: bateu ou não bateu. Quando não bate, o `ddf` calcula a
diferença entre os nomes de coluna do override antigo e os nomes de coluna atuais para
produzir uma mensagem específica: quais colunas foram adicionadas, quais foram removidas.
Quando os nomes de coluna são exatamente os mesmos mas o hash ainda diverge, a mensagem
cai para um caso genérico ("algo estrutural mudou, mas os nomes de coluna foram
preservados"), sem apontar qual campo específico mudou em qual coluna (um `VARCHAR(50)`
que virou `VARCHAR(100)`, por exemplo, não gera uma mensagem dizendo isso).

É uma limitação real, não uma omissão de texto: o hash foi desenhado para responder "mudou
ou não mudou", e o diff de nomes de coluna é a única granularidade adicional construída em
cima dele. Diagnosticar exatamente qual campo mudou, hoje, é trabalho de quem lê o diff do
schema na fonte, não algo que o `ddf` aponta automaticamente.

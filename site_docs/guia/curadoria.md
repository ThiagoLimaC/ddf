# Curadoria (overrides)

A curadoria é a etapa 6-7 do wizard, logo depois da extração: o `ddf` gera ou atualiza um
arquivo YAML por tabela e pausa a execução para você revisar e preencher.

## O que é um override

Um override é o arquivo YAML onde fica a curadoria humana de uma tabela: papel de
negócio e regras de negócio, tanto no nível da tabela quanto no de cada coluna. É o
único lugar do `ddf` onde conhecimento que não está no schema (o que a tabela representa
para o negócio, que regra uma coluna deveria seguir) entra no pipeline.

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

`hash` é calculado pelo `ddf` a partir da estrutura da tabela (colunas, tipos, chaves,
restrições) e nunca deve ser editado à mão: é o que decide, na próxima execução, se esse
override ainda corresponde à tabela que ele descreve.

## Onde fica

Cada override mora em `<diretório-escolhido>/<escopo>/<tabela>.yaml`. O diretório raiz é
perguntado no wizard; a subestrutura por escopo e tabela é sempre a mesma, para que um
override seja fácil de achar a partir do nome da tabela.

## Skeleton na primeira execução

Na primeira vez que uma tabela é extraída, o `ddf` cria o override dela automaticamente,
com `papel_de_negocio` e `regras_de_negocio` em branco, uma entrada por coluna. Depois de
gerar (ou atualizar) todos os skeletons pendentes, o wizard pausa:

```
Edite os YAMLs de overrides em '/caminho/absoluto/overrides' e aperte uma tecla
para continuar...
```

É o momento de abrir os arquivos e preencher a curadoria. Um preenchimento mínimo (papel
de negócio da tabela e de algumas colunas) já é suficiente para seguir; nada impede
voltar e completar o resto em uma execução futura.

## O que sobrevive à reextração

Reextrair a mesma fonte não apaga a curadoria já feita. A cada execução, o `ddf` calcula
o hash estrutural atual da tabela e compara com o `hash` gravado no override:

- Se os dois batem, a estrutura não mudou. O override é aplicado como está, sem
  reescrever o arquivo.
- Se os dois divergem, alguma coisa estrutural mudou (uma coluna foi adicionada ou
  removida, ou algum outro campo estrutural, como tipo ou chave, foi alterado sem mudar
  nomes de coluna). O `ddf` atualiza o skeleton, preservando a curadoria das colunas que
  continuam existindo, e avisa exatamente o que mudou: colunas adicionadas, colunas
  removidas, ou a constatação de que algo estrutural mudou mesmo com os nomes de coluna
  preservados.

Curadoria de uma coluna removida da fonte é descartada junto com a coluna; curadoria de
colunas que continuam existindo nunca é perdida por uma reextração.

Como o hash é calculado por dentro, e o porquê de cada escolha de implementação, estão em
[Hash estrutural](../arquitetura/hash-estrutural.md).

## Próximo passo

Com os overrides aplicados, o `ddf` monta o banco curado que alimenta a análise. Ver
[Analisadores (métricas)](analisadores.md) para o que é calculado a partir daqui, e
[Artefatos gerados](../artefatos/index.md) para onde papel de negócio e regras de negócio
aparecem no resultado final.

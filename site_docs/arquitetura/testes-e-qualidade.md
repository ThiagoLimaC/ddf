# Testes e qualidade

Rigor de teste não é um item adicionado depois que a arquitetura já estava pronta: é parte
do mesmo pacote de decisões de engenharia que confina métrica a Value Object ou torna
`OrquestradorDeTabelas` uma Porta desde a v1. A mesma disciplina de backend que evita
acoplamento desnecessário entre componentes é o que decide o que entra, e o que fica de
fora, da suíte de testes.

## Guard-rails de lint e CI

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "D"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.mypy]
strict = true
```

CI roda `ruff`, `mypy --strict` e `pytest` a cada push, desde o primeiro PR mergeado no
projeto. Nenhum PR entra com o pipeline vermelho. `mypy --strict` não é só checagem de
tipo: os quatro tipos do pipeline (`TabelaExtraida`, `TabelaCurada`, `BancoCurado`,
`BancoAnalisado`) são estruturalmente distintos, então `mypy` rejeita em tempo de
verificação qualquer composição de estágios que tente pular uma etapa. Um Gerador que
tentasse ler `TabelaCurada` diretamente, por exemplo, não compila.

## Três categorias obrigatórias, por Estágio e por Adapter

Todo `Estagio` (Extrator, Analisador, Sobrescrita, Gerador, `OrquestradorParalelo`,
`compor()`) e todo Adapter novo precisa de, no mínimo:

1. **Caminho feliz**: comportamento esperado com entrada válida e representativa.
2. **Erro esperado**: falha de domínio real devolvendo `Falha`, nunca uma exceção solta.
3. **Borda**: caso limite real do domínio: tabela vazia, coluna sem dado na amostra,
   valor com caractere especial, FK fora da extração atual, amostra menor que o
   `tamanho_amostra` configurado.

O que não conta como borda: um caso que `mypy --strict` já rejeita em tempo de
verificação. Testar isso de novo em runtime seria redundante com uma garantia que o
tipador já oferece de graça.

Cada arquivo `test_*.py` agrupa as três categorias em classes (`TestFeliz`, `TestErro`,
`TestBorda`) dentro do mesmo arquivo, não em arquivos físicos separados: um módulo de
produção pequeno não deveria virar três arquivos de teste fragmentados. Categoria sem
teste aplicável simplesmente não vira classe: sem stub vazio "porque a convenção pede".

## A pergunta que decide se um teste entra na suíte

"Que bug real ou regra de negócio este teste pegaria, que não seria pego de outra forma
(tipo, lint, teste já existente)?" Se a resposta é "nenhum", o teste não entra. A mesma
disciplina de concisão que vale para código de produção vale para a suíte: um teste que
não pega bug real é manutenção paga sem retorno.

## Testabilidade por isolamento

Como cada `Estagio` recebe um tipo conhecido e devolve um `Resultado` de um tipo
conhecido, testar um Analisador novo não exige montar o pipeline inteiro: só chamar o
`Estagio` com a entrada que o próprio tipo já declara. É consequência direta de estágios
compostos e tipados (ver [Pipeline e paralelismo](pipeline-e-paralelismo.md)): a mesma
decisão que facilita adicionar um Estágio novo também facilita testá-lo sem infraestrutura
extra.

Testes de CLI seguem a mesma lógica de fronteira: injetam um `Extrator` fake através de
`EXTRATORES_REGISTRADOS`, nunca mockam `psycopg2.connect` ou o driver de baixo nível
diretamente. O que está sob teste é o comportamento da CLI contra a Porta, não o
comportamento do driver.

## Open/Closed como teste, não só como princípio citado

Sempre que uma Porta ganha uma implementação nova, existe pelo menos um teste que prova
que adicioná-la não exigiu editar nenhuma implementação já existente, incluindo
Analisadores: um teste instancia um Analisador novo, adiciona ao `compor()`, e verifica que
os Analisadores já existentes continuam produzindo exatamente o mesmo resultado de antes.

É a mesma verificação, num nível mais amplo, que sustenta a promessa de extensão por
plugin de terceiro (ver [Extensão via plugins](../extensao.md)): o mecanismo de
`entry_points` só é confiável porque um teste real prova que um Adapter novo, nativo ou de
terceiro, se conecta sem exigir mudança em nenhum Adapter existente, não porque a
documentação afirma que "deveria funcionar assim".

# Extensão via plugins

Um plugin de terceiro no `ddf` funciona como uma peça de Lego: encaixa numa Porta já
existente sem exigir nenhuma alteração na estrutura em volta. Um `Extrator` novo ou um
`Gerador` novo entra no wizard do mesmo jeito que `ExtratorPostgres` ou `GeradorDbt` já
entram, e nenhum dos dois é tratado como cidadão de segunda classe: os Adapters nativos da
v1 passam pela mesma via de descoberta que um plugin de terceiro usaria.

## Como o encaixe funciona

`Extrator` e `Gerador` são reexportados em `domain/ports/__init__.py` como caminho de
import público, e descobertos via `importlib.metadata.entry_points`, nos grupos
`ddf.extratores` e `ddf.geradores`. Um pacote instalado que declara um entry point nesses
grupos é encontrado automaticamente na próxima execução do `ddf`, sem precisar registrar
nada manualmente dentro do projeto.

Um entry point de `ddf.extratores` aponta para uma instância de `ExtratorRegistrado`
(classe do Extrator, mais a função que sabe construí-lo interativamente perguntando
credenciais). Um entry point de `ddf.geradores` aponta para uma classe de `Gerador` com
construtor sem argumentos. `mypy --strict` valida os dois contra o `Protocol`
correspondente em tempo de desenvolvimento do plugin; o `ddf` valida de novo em tempo de
execução (`issubclass`/`isinstance`), e isola qualquer plugin que falhe nessa checagem como
um `Aviso`, sem impedir que os demais plugins e os Adapters nativos continuem funcionando.

```toml
# pyproject.toml de um plugin de terceiro (esqueleto mínimo)
[project]
name = "ddf-extrator-sqlite"
version = "0.1.0"
dependencies = ["ddf-framework"]

[project.entry-points."ddf.extratores"]
SQLite = "ddf_extrator_sqlite.registro:_REGISTRO_SQLITE"
```

```python
# ddf_extrator_sqlite/registro.py
from ddf.domain.ports.extrator import ExtratorRegistrado

from .extrator_sqlite import ExtratorSQLite, construir_extrator_sqlite

_REGISTRO_SQLITE = ExtratorRegistrado(
    classe_extrator=ExtratorSQLite,
    construir=construir_extrator_sqlite,
)
```

Com o pacote instalado (`pip install ddf-extrator-sqlite`), "SQLite" aparece como opção de
fonte no wizard, ao lado de PostgreSQL e MariaDB, sem nenhuma mudança em código do `ddf`
em si. O mesmo teste que garante isso (um Adapter novo adicionado sem editar nenhum
Adapter existente) é descrito em [Testes e qualidade](arquitetura/testes-e-qualidade.md).

## O tamanho real da peça

A analogia de Lego descreve o mecanismo de encaixe corretamente, mas não descreve o
tamanho da peça que se encaixa. Escrever um `Extrator` novo de verdade tem um custo real,
que vale deixar explícito em vez de sugerir que "implementar o `Protocol`" é o trabalho
inteiro.

`extractors/comum/` cobre uma fração pequena do volume de um Extrator. Entre
`ExtratorPostgres` e `ExtratorMariaDB`, o código compartilhado em `extractors/comum/`
soma cerca de 15% do total de linhas dos dois; o resto é específico de cada motor. A
lógica de paralelismo intra-tabela, em particular, foi deixada deliberadamente fora do
código compartilhado: o ciclo de vida de conexão e a semântica de particionamento
divergem demais entre os dois motores para compensar a unificação (física, via `ctid`, no
Postgres; lógica, via faixa de chave primária, no MariaDB, ver
[Pipeline e paralelismo](arquitetura/pipeline-e-paralelismo.md)). Um terceiro Extrator
relacional (SQL Server, Oracle) herda esse padrão de divisão, não o trabalho já feito para
Postgres e MariaDB.

Suporte pleno como destino do `GeradorDbt` é uma segunda frente de trabalho. Um
`Extrator` novo entra no wizard e produz `TabelaExtraida` corretamente sem precisar de
nada além do `Protocol`. Mas para o projeto dbt gerado a partir dele *rodar de verdade*
contra esse motor novo, o `GeradorDbt` precisa de templates Jinja próprios por motor,
o mesmo padrão `adapter.dispatch` que hoje distingue `postgres__cast_type.sql` de
`mariadb__cast_type.sql` (ver [Tecnologias](arquitetura/tecnologias.md#jinja2)). Quem lê só
a Porta `Extrator` não descobre essa dependência: ela vive inteiramente do lado do
`GeradorDbt`.

O Port `Extrator` pressupõe hierarquia relacional com catálogo consultável. Os métodos
de `Extrator` (`listar_escopos`, `listar_tabelas`, `extrair_tabela`) descrevem uma
estrutura de schema → tabela → coluna, com um catálogo interrogável para obter tipo,
chave e restrição. Isso é neutro entre os bancos relacionais reais que o `ddf` já
suporta, mas não é necessariamente neutro para uma fonte não-relacional (um arquivo, uma
API). É o escopo atual da Porta, não uma limitação escondida.

## Contribua conosco

Se você tem uma fonte de dados ou um formato de artefato que o `ddf` ainda não cobre, o
caminho é abrir uma issue ou um PR implementando o `Protocol` correspondente. O mesmo
mecanismo de entry points descrito acima funciona tanto para um pacote publicado à parte
quanto para um Adapter incorporado ao próprio repositório do `ddf`. Repositório e issues:
[github.com/ThiagoLimaC/ddf](https://github.com/ThiagoLimaC/ddf).

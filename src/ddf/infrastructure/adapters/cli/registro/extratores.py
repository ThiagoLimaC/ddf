"""Registro de Extratores de dados disponíveis para o wizard da CLI.

Os Extratores nativos (PostgreSQL/MariaDB) não se registram aqui por
chamada direta — são descobertos via entry points do grupo "ddf.extratores"
(declarados em `pyproject.toml`, apontando para `_REGISTRO_POSTGRES`/
`_REGISTRO_MARIADB` abaixo), a mesma via de um plugin de terceiro. Ver
`cli/registro/descoberta.py`.
"""

from collections.abc import Callable
from ipaddress import AddressValueError, IPv6Address
from urllib.parse import quote

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)

EXTRATORES_REGISTRADOS: dict[str, ExtratorRegistrado] = {}

# Máscara de largura fixa para a senha na árvore de decisão — nunca
# "*" * len(senha_conexao), que denunciaria o tamanho real da senha.
_MASCARA_SENHA = "****"

# OrquestradorParalelo() no wizard usa max_trabalhadores=8 (default, não
# exposto — ver wizard.py). Se max_conexoes do Extrator também fosse 8, as
# 8 conexões já estariam em uso por outras tabelas no instante em que uma
# tabela grande tenta reservar as suas pro paralelismo intra-tabela —
# reservar_conexoes nunca acharia as 2 mínimas livres, e o caminho
# paralelo nunca ativaria de verdade sob carga concorrente (degradação
# graciosa pro sequencial, sem erro, mas silenciosamente inútil). +4 dá
# folga pro caso pior (todos os 8 trabalhadores ocupados ao mesmo tempo)
# ainda conseguir o `max_conexoes_por_tabela` padrão inteiro. Vale pros
# dois motores — mesmo `max_trabalhadores` do Orquestrador compete pelo
# semáforo dos dois.
_MAX_CONEXOES_POSTGRES = 12
_MAX_CONEXOES_MARIADB = 12


def registrar_extrator(
    nome: str,
    classe_extrator: type[Extrator],
    construir: Callable[[ConfiguracaoDeExtracao], Extrator],
    registro: dict[str, ExtratorRegistrado] = EXTRATORES_REGISTRADOS,
) -> None:
    """Registra um novo Extrator no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: Identificador do Extrator exibido ao usuário no wizard.
        classe_extrator: Classe de Extrator associada ao registro.
        construir: Função que constrói uma instância do Extrator a partir de
            uma ConfiguracaoDeExtracao já resolvida — responsável por
            perguntar interativamente as credenciais/parâmetros específicos
            dessa fonte.
        registro: Dicionário onde o Extrator é registrado. Usa
            EXTRATORES_REGISTRADOS por padrão.
    """
    registrar_ou_falhar(
        nome,
        "Extrator",
        ExtratorRegistrado(classe_extrator=classe_extrator, construir=construir),
        registro,
    )


def _formatar_host(host: str) -> str:
    """Envolve um host IPv6 literal entre colchetes, exigido pelo formato de DSN.

    Sem isso, `host:porta` fica ambíguo/inválido para IPv6 (`::1:5432` não
    tem como saber onde o endereço termina e a porta começa) — a URI
    padrão exige `[::1]:5432`. Hostname/IPv4 (o caso comum, incluindo
    endpoints da AWS RDS — sempre hostname, nunca IPv6 bruto) passam
    intactos.
    """
    try:
        IPv6Address(host)
    except AddressValueError:
        return host
    return f"[{host}]"


def _construir_extrator_postgres(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta host/porta/credenciais do Postgres e monta o ExtratorPostgres.

    Campos separados (não uma connection string inteira) pra que a senha
    passe por `prompts.senha()` — mascarada, em vez de aparecer em texto
    claro na tela/scrollback. Usuário/senha/banco passam por `quote` antes
    de compor a DSN, já que podem conter caracteres especiais de URL
    (`@`, `:`, `/`, `%`).

    Parâmetros extra (opcional) cobrem o que os campos fixos não expressam
    — principalmente `sslmode`, comum em Postgres gerenciado (RDS, Azure
    Database, PgBouncer).

    A árvore de decisão (Fonte/Host/Porta/Banco/Usuário/Senha) só é
    impressa aqui no final, depois de coletado todo parâmetro.
    """
    host = prompts.texto("Host do Postgres:")
    porta = prompts.numero("Porta:", int, default="5432")
    banco = prompts.texto("Banco de dados:")
    usuario = prompts.texto("Usuário:")
    senha_conexao = prompts.senha("Senha:")
    parametros_extra = prompts.texto(
        "Parâmetros extra de conexão (opcional, ex.: sslmode=require):",
        default="",
    )
    dsn = (
        f"postgresql://{quote(usuario, safe='')}:{quote(senha_conexao, safe='')}"
        f"@{_formatar_host(host)}:{porta}/{quote(banco, safe='')}"
    )
    if parametros_extra:
        dsn += f"?{parametros_extra}"
    print()
    prompts.linha_de_decisao("Fonte", "PostgreSQL")
    prompts.linha_de_decisao("Host", host)
    prompts.linha_de_decisao("Porta", str(porta))
    prompts.linha_de_decisao("Banco", banco)
    prompts.linha_de_decisao("Usuário", usuario)
    prompts.linha_de_decisao("Senha", _MASCARA_SENHA, ultimo=True)
    return ExtratorPostgres(
        dsn=dsn, configuracao=configuracao, max_conexoes=_MAX_CONEXOES_POSTGRES
    )


def _construir_extrator_mariadb(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta host/porta/credenciais do MariaDB e monta o ExtratorMariaDB.

    A árvore de decisão (Fonte/Host/Porta/Usuário/Senha) só é impressa aqui
    no final, depois de coletado todo parâmetro — mesmo padrão de
    `_construir_extrator_postgres`.
    """
    host = prompts.texto("Host do MariaDB:")
    porta = prompts.numero("Porta:", int, default="3306")
    usuario = prompts.texto("Usuário:")
    senha_conexao = prompts.senha("Senha:")
    print()
    prompts.linha_de_decisao("Fonte", "MariaDB")
    prompts.linha_de_decisao("Host", host)
    prompts.linha_de_decisao("Porta", str(porta))
    prompts.linha_de_decisao("Usuário", usuario)
    prompts.linha_de_decisao("Senha", _MASCARA_SENHA, ultimo=True)
    return ExtratorMariaDB(
        host=host,
        port=porta,
        user=usuario,
        password=senha_conexao,
        configuracao=configuracao,
        max_conexoes=_MAX_CONEXOES_MARIADB,
    )


_REGISTRO_POSTGRES = ExtratorRegistrado(
    classe_extrator=ExtratorPostgres, construir=_construir_extrator_postgres
)
_REGISTRO_MARIADB = ExtratorRegistrado(
    classe_extrator=ExtratorMariaDB, construir=_construir_extrator_mariadb
)

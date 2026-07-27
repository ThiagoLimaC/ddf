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

    Campos separados (não uma connection string inteira) para que a senha
    passe por `prompts.senha()` — mascarada, mesmo tratamento do MariaDB —
    em vez de aparecer em texto claro na tela/scrollback do terminal.
    Usuário/senha/banco passam por `quote` antes de compor a DSN: qualquer
    um pode conter caracteres especiais de URL (`@`, `:`, `/`, `%`) que
    quebrariam o formato se inseridos crus.

    Parâmetros extra (opcional) cobrem o que campos fixos não expressam —
    principalmente `sslmode`, comum/exigido por Postgres gerenciado em
    produção (RDS, Azure Database, PgBouncer na frente) — sem voltar a
    pedir a connection string inteira em texto claro.
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
    return ExtratorPostgres(dsn=dsn, configuracao=configuracao)


def _construir_extrator_mariadb(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta host/porta/credenciais do MariaDB e monta o ExtratorMariaDB."""
    host = prompts.texto("Host do MariaDB:")
    porta = prompts.numero("Porta:", int, default="3306")
    usuario = prompts.texto("Usuário:")
    senha_conexao = prompts.senha("Senha:")
    return ExtratorMariaDB(
        host=host,
        port=porta,
        user=usuario,
        password=senha_conexao,
        configuracao=configuracao,
    )


_REGISTRO_POSTGRES = ExtratorRegistrado(
    classe_extrator=ExtratorPostgres, construir=_construir_extrator_postgres
)
_REGISTRO_MARIADB = ExtratorRegistrado(
    classe_extrator=ExtratorMariaDB, construir=_construir_extrator_mariadb
)

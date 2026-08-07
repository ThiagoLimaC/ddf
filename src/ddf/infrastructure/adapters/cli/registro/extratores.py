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

# Máscara de largura fixa para a senha na árvore de decisão da etapa de
# conexão — nunca "*" * len(senha_conexao). O comprimento da senha mascarada
# ainda seria uma pista sobre ela (ex.: "****" vs "********************"
# denuncia senha curta vs. longa/gerada), então a árvore sempre mostra o
# mesmo texto fixo, independente do valor real.
_MASCARA_SENHA = "****"


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

    A árvore de decisão da etapa de conexão (Fonte/Host/Porta/Banco/
    Usuário/Senha) só é impressa aqui no final, depois de coletado todo o
    parâmetro — ver `linha_de_decisao` para o porquê deste ser o único
    ponto do wizard que fecha o bloco com `└─` em vez de `├─`.
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
    return ExtratorPostgres(dsn=dsn, configuracao=configuracao)


def _construir_extrator_mariadb(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta host/porta/credenciais do MariaDB e monta o ExtratorMariaDB.

    A árvore de decisão da etapa de conexão (Fonte/Host/Porta/Usuário/Senha)
    só é impressa aqui no final, depois de coletado todo o parâmetro — ver
    `_construir_extrator_postgres`/`linha_de_decisao` para o porquê.
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
    )


_REGISTRO_POSTGRES = ExtratorRegistrado(
    classe_extrator=ExtratorPostgres, construir=_construir_extrator_postgres
)
_REGISTRO_MARIADB = ExtratorRegistrado(
    classe_extrator=ExtratorMariaDB, construir=_construir_extrator_mariadb
)

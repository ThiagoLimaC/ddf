"""Registro de Extratores de dados disponíveis para o wizard da CLI.

Os Extratores nativos (PostgreSQL/MariaDB) não se registram aqui por
chamada direta — são descobertos via entry points do grupo "ddf.extratores"
(declarados em `pyproject.toml`, apontando para `_REGISTRO_POSTGRES`/
`_REGISTRO_MARIADB` abaixo), a mesma via de um plugin de terceiro. Ver
`cli/registro/descoberta.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.extractors.mariadb.extrator_mariadb import (
    ExtratorMariaDB,
)
from ddf.infrastructure.adapters.extractors.postgres.extrator_postgres import (
    ExtratorPostgres,
)


@dataclass(frozen=True)
class ExtratorRegistrado:
    """Um Extrator registrado, junto da função que sabe construí-lo interativamente."""

    classe_extrator: type[Extrator]
    construir: Callable[[ConfiguracaoDeExtracao], Extrator]


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


def _construir_extrator_postgres(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta a connection string do Postgres e monta o ExtratorPostgres."""
    dsn = prompts.texto(
        "Connection string do Postgres:",
        default="postgresql://usuario:senha@host:porta/banco",
        dica_limpar=True,
    )
    return ExtratorPostgres(dsn=dsn, configuracao=configuracao)


def _construir_extrator_mariadb(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Pergunta host/porta/credenciais do MariaDB e monta o ExtratorMariaDB."""
    host = prompts.texto("Host do MariaDB:")
    porta = int(prompts.texto("Porta:", default="3306"))
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

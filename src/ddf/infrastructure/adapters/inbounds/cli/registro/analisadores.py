"""Registro de Analisadores disponíveis para o wizard da CLI.

Ponto de extensão manipulado só por quem desenvolve o ddf — nunca exposto
em nenhum menu do wizard, que sempre roda todos os Analisadores
registrados, sem seleção do usuário. Ao contrário de Extrator/Gerador,
deliberadamente **não** entra na descoberta via entry points: Analisador é
a ACL entre Curation e Analysis (`CLAUDE.md`), e abrir descoberta
automática de terceiro pra ele rodaria código de qualquer pacote instalado
no venv em toda execução, sem o usuário ter pedido.
"""

from ddf.domain.ports.analisador import Analisador
from ddf.infrastructure.adapters.inbounds.cli.registro.comum import registrar_ou_falhar
from ddf.infrastructure.adapters.outbounds.analyzers.analisador_de_metricas_de_coluna import (
    AnalisadorDeMetricasDeColuna,
)
from ddf.infrastructure.adapters.outbounds.analyzers.analisador_de_metricas_de_tabela import (
    AnalisadorDeMetricasDeTabela,
)

ANALISADORES_REGISTRADOS: dict[str, Analisador] = {}


def registrar_analisador(
    nome: str,
    analisador: Analisador,
    registro: dict[str, Analisador] = ANALISADORES_REGISTRADOS,
) -> None:
    """Registra um novo Analisador no wizard.

    Levanta ValueError se `nome` já estiver registrado em `registro`.

    Args:
        nome: identificador interno do Analisador no registro — nunca
            exibido em nenhum menu do wizard; existe para mensagens de
            log/erro.
        analisador: instância do Analisador (construtor sem argumentos).
        registro: Dicionário onde o Analisador é registrado. Usa
            ANALISADORES_REGISTRADOS por padrão.
    """
    registrar_ou_falhar(nome, "Analisador", analisador, registro)


registrar_analisador("MetricasDeColuna", AnalisadorDeMetricasDeColuna())
registrar_analisador("MetricasDeTabela", AnalisadorDeMetricasDeTabela())

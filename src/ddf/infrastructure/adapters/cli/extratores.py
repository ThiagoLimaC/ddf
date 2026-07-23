"""Registro de Extratores de dados disponíveis para o wizard da CLI."""

from collections.abc import Callable
from dataclasses import dataclass

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator


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
    if nome in registro:
        raise ValueError(f"Extrator '{nome}' já está registrado.")
    registro[nome] = ExtratorRegistrado(
        classe_extrator=classe_extrator, construir=construir
    )

"""Fixtures de plugin de Extrator (válido/inválido), usadas só em test_descoberta."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.ports.extrator import Extrator
from ddf.infrastructure.adapters.cli.registro.extratores import ExtratorRegistrado


class ExtratorPluginFake:
    """Extrator fake que simula um plugin de terceiro descoberto via entry point."""

    def listar_escopos(self) -> object:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        ...

    def listar_tabelas(self, escopo: str) -> object:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        ...

    def extrair_tabela(self, escopo: str, tabela: str) -> object:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        ...


class NaoSatisfazExtrator:
    """Classe sem os métodos exigidos pelo Protocol Extrator — caso de erro."""


def _construir(configuracao: ConfiguracaoDeExtracao) -> Extrator:
    """Construtor fake usado só pela descoberta nos testes."""
    return ExtratorPluginFake()


REGISTRO_VALIDO = ExtratorRegistrado(
    classe_extrator=ExtratorPluginFake, construir=_construir
)
REGISTRO_INVALIDO = ExtratorRegistrado(
    classe_extrator=NaoSatisfazExtrator,  # type: ignore[arg-type]
    construir=_construir,
)

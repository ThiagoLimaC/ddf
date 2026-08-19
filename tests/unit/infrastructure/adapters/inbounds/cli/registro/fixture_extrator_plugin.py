"""Fixtures de plugin de Extrator (válido/inválido), usadas só em test_descoberta."""

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.domain.shared.resultado import Resultado


class ExtratorPluginFake:
    """Extrator fake que simula um plugin de terceiro descoberto via entry point."""

    def listar_escopos(self) -> Resultado[list[str]]:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        raise NotImplementedError

    def listar_tabelas(self, escopo: str, /) -> Resultado[list[tuple[str, str]]]:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        raise NotImplementedError

    def extrair_tabela(
        self, escopo: str, tabela: str, /
    ) -> Resultado[TabelaExtraida]:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        raise NotImplementedError


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

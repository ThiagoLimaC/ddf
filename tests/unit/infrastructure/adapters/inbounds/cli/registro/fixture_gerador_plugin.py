"""Fixtures de plugin de Gerador (válido/inválido), usadas só por test_descoberta.py."""

from pathlib import Path

from ddf.domain.model.analysis import BancoAnalisado, TipoDeMetrica
from ddf.domain.shared.resultado import Resultado


class GeradorPluginFake:
    """Gerador fake que simula um plugin de terceiro descoberto via entry point."""

    requer: list[TipoDeMetrica] = []

    def __call__(
        self, entrada: BancoAnalisado, destino: Path, /
    ) -> Resultado[None]:
        """Não é exercitado pela descoberta — não precisa de corpo real."""
        raise NotImplementedError


class NaoSatisfazGerador:
    """Classe sem os métodos/atributos exigidos pelo Protocol Gerador — caso de erro."""

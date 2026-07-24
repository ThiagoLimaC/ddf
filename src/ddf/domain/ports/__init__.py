"""Protocols que definem os pontos de extensão do pipeline."""

from ddf.domain.ports.extrator import Extrator, ExtratorRegistrado
from ddf.domain.ports.gerador import Gerador

__all__ = ["Extrator", "ExtratorRegistrado", "Gerador"]

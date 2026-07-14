"""Configuração de extração compartilhada por todos os Extratores."""

from pydantic import BaseModel, InstanceOf

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem


class ConfiguracaoDeExtracao(BaseModel):
    """Parâmetros de extração agnósticos de fonte, escolhidos pelo usuário."""

    estrategia: InstanceOf[EstrategiaDeAmostragem]

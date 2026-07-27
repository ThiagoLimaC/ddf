"""Configuração de extração compartilhada por todos os Extratores."""

from pydantic import BaseModel, InstanceOf

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem


class ConfiguracaoDeExtracao(BaseModel):
    """Parâmetros de extração agnósticos de fonte, escolhidos pelo usuário.

    `estrategia` é opcional na construção porque o wizard da CLI conecta e
    lista escopos antes de perguntar a estratégia de amostragem — só é
    exigida de fato em `Extrator.extrair_tabela`, nunca em
    `listar_escopos`/`listar_tabelas`. Ausência tratada como `Falha` pelo
    Extrator, não propagada como erro de validação aqui.
    """

    estrategia: InstanceOf[EstrategiaDeAmostragem] | None = None

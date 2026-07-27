"""Configuração de extração compartilhada por todos os Extratores."""

from pydantic import BaseModel, InstanceOf

from ddf.domain.ports.estrategia_de_amostragem import EstrategiaDeAmostragem
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


class ConfiguracaoDeExtracao(BaseModel):
    """Parâmetros de extração agnósticos de fonte, escolhidos pelo usuário.

    `estrategia` é opcional na construção porque o wizard da CLI conecta e
    lista escopos antes de perguntar a estratégia de amostragem — só é
    exigida de fato em `Extrator.extrair_tabela`, nunca em
    `listar_escopos`/`listar_tabelas`. Ausência tratada como `Falha` pelo
    Extrator, não propagada como erro de validação aqui.
    """

    estrategia: InstanceOf[EstrategiaDeAmostragem] | None = None

    def estrategia_obrigatoria(self) -> Resultado[EstrategiaDeAmostragem]:
        """Devolve `estrategia` ou `Falha` se ainda não foi configurada.

        Centraliza a checagem que todo `Extrator.extrair_tabela` precisa
        fazer — sem isso, cada Adapter concreto (Postgres, MariaDB, e
        futuros plugins de terceiro) precisaria copiar o mesmo `if
        estrategia is None` manualmente, sem nada que force um novo
        Extrator a lembrar de replicar a checagem (issue #75).
        """
        if self.estrategia is None:
            return Falha("Extrator usado sem estratégia de amostragem configurada.")
        return Sucesso(self.estrategia)

"""Orquestração paralela de extração e aplicação de sobrescritas."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.estagio import Estagio

_Item = TypeVar("_Item")
_Saida = TypeVar("_Saida")


def _mensagem_falha_agregada(
    verbo: str,
    quantidade_falhas: int,
    total: int,
    falhas: list[tuple[str, str]],
) -> str:
    """Monta a mensagem agregada de Falha a partir das falhas individuais coletadas.

    Args:
        verbo: ação que falhou (ex.: "extrair", "aplicar sobrescritas em").
        quantidade_falhas: nº de itens que falharam.
        total: nº total de itens processados nesta fase.
        falhas: pares (identificador, mensagem de erro) de cada falha.

    Returns:
        Mensagem única, com cada falha unida por "; ".
    """
    itens = "; ".join(f"{identificador}: {erro}" for identificador, erro in falhas)
    return f"Falha ao {verbo} {quantidade_falhas} de {total} tabelas: {itens}"


class OrquestradorParalelo:
    """Coordena extração e aplicação de sobrescritas em paralelo via threads."""

    def __init__(self, max_trabalhadores: int = 8) -> None:
        """Guarda o teto de threads usadas para paralelizar as duas fases.

        Args:
            max_trabalhadores: nº máximo de chamadas concorrentes por fase —
                higiene de recurso local, sem relação com concorrência segura
                contra a fonte (cada Extrator concreto já garante isso
                internamente).

        Raises:
            ValueError: se `max_trabalhadores` não for positivo.
        """
        if max_trabalhadores <= 0:
            raise ValueError(
                f"max_trabalhadores deve ser positivo ({max_trabalhadores})."
            )
        self._max_trabalhadores = max_trabalhadores

    def _executar_em_paralelo(
        self,
        itens: list[_Item],
        funcao: Callable[[_Item], Resultado[_Saida]],
        identificador: Callable[[_Item], str],
    ) -> tuple[list[_Saida], list[tuple[str, str]]]:
        """Executa `funcao` em paralelo sobre `itens`, acumulando sucessos e falhas.

        Args:
            itens: itens de entrada, um por chamada de `funcao`.
            funcao: transformação aplicada a cada item, retornando um Resultado.
            identificador: extrai o identificador textual de um item, usado
                para nomear o item numa falha.

        Returns:
            Tupla (sucessos, falhas) — falhas como (identificador, erro).
        """
        sucessos: list[_Saida] = []
        falhas: list[tuple[str, str]] = []

        with ThreadPoolExecutor(max_workers=self._max_trabalhadores) as executor:
            futuros = {executor.submit(funcao, item): item for item in itens}
            for futuro in as_completed(futuros):
                item = futuros[futuro]
                resultado = futuro.result()
                if isinstance(resultado, Falha):
                    falhas.append((identificador(item), resultado.erro))
                    continue
                sucessos.append(resultado.valor)

        return sucessos, falhas

    def extrair(
        self, schemas: list[str], extrator: Extrator
    ) -> Resultado[list[TabelaExtraida]]:
        """Lista e extrai, em paralelo, todas as tabelas dos schemas informados.

        Args:
            schemas: schemas cujas tabelas serão listadas e extraídas.
            extrator: Extrator concreto usado para listar/extrair cada tabela.

        Returns:
            Sucesso com list[TabelaExtraida] ordenada por (nome_schema,
            nome_tabela), ou Falha agregada se algum schema/tabela falhou.
        """
        pares_a_extrair: list[tuple[str, str]] = []
        falhas_listagem: list[tuple[str, str]] = []

        for schema in schemas:
            resultado_listagem = extrator.listar_tabelas(schema)
            if isinstance(resultado_listagem, Falha):
                falhas_listagem.append((schema, resultado_listagem.erro))
                continue
            pares_a_extrair.extend(resultado_listagem.valor)

        total = len(pares_a_extrair) + len(falhas_listagem)
        tabelas, falhas_extracao = self._executar_em_paralelo(
            pares_a_extrair,
            lambda par: extrator.extrair_tabela(*par),
            lambda par: f"{par[0]}.{par[1]}",
        )
        falhas = falhas_listagem + falhas_extracao

        if falhas:
            return Falha(
                _mensagem_falha_agregada("extrair", len(falhas), total, falhas)
            )

        tabelas.sort(key=lambda tabela: (tabela.nome_schema, tabela.nome_tabela))
        return Sucesso(tabelas)

    def aplicar_sobrescritas(
        self,
        tabelas: list[TabelaExtraida],
        sobrescrita: Estagio[TabelaExtraida, TabelaCurada],
    ) -> Resultado[BancoCurado]:
        """Aplica, em paralelo, a Sobrescrita sobre cada TabelaExtraida.

        Args:
            tabelas: tabelas extraídas a curar.
            sobrescrita: Estagio que traduz TabelaExtraida em TabelaCurada.

        Returns:
            Sucesso com BancoCurado (tabelas ordenadas por (nome_schema,
            nome_tabela)), ou Falha agregada se alguma tabela falhou.
        """
        total = len(tabelas)
        tabelas_curadas, falhas = self._executar_em_paralelo(
            tabelas,
            sobrescrita,
            lambda tabela: f"{tabela.nome_schema}.{tabela.nome_tabela}",
        )

        if falhas:
            return Falha(
                _mensagem_falha_agregada(
                    "aplicar sobrescritas em", len(falhas), total, falhas
                )
            )

        tabelas_curadas.sort(
            key=lambda tabela: (tabela.nome_schema, tabela.nome_tabela)
        )
        return Sucesso(BancoCurado(tabelas=tabelas_curadas))

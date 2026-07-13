"""Orquestração paralela de extração e aplicação de sobrescritas."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ddf.domain.model.curation import BancoCurado, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso
from ddf.pipeline.estagio import Estagio


def _mensagem_falha_agregada(
    verbo: str,
    quantidade_falhas: int,
    total: int,
    falhas: list[tuple[str, str]],
) -> str:
    """Monta a mensagem agregada de Falha a partir das falhas individuais coletadas."""
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
        """
        self._max_trabalhadores = max_trabalhadores

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
        falhas: list[tuple[str, str]] = []

        for schema in schemas:
            resultado_listagem = extrator.listar_tabelas(schema)
            if isinstance(resultado_listagem, Falha):
                falhas.append((schema, resultado_listagem.erro))
                continue
            pares_a_extrair.extend(resultado_listagem.valor)

        total = len(pares_a_extrair) + len(falhas)
        tabelas: list[TabelaExtraida] = []

        with ThreadPoolExecutor(max_workers=self._max_trabalhadores) as executor:
            futuros = {
                executor.submit(extrator.extrair_tabela, schema, tabela): (
                    schema,
                    tabela,
                )
                for schema, tabela in pares_a_extrair
            }
            for futuro in as_completed(futuros):
                schema, tabela = futuros[futuro]
                resultado = futuro.result()
                if isinstance(resultado, Falha):
                    falhas.append((f"{schema}.{tabela}", resultado.erro))
                    continue
                tabelas.append(resultado.valor)

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
        tabelas_curadas: list[TabelaCurada] = []
        falhas: list[tuple[str, str]] = []

        with ThreadPoolExecutor(max_workers=self._max_trabalhadores) as executor:
            futuros = {
                executor.submit(sobrescrita, tabela): tabela for tabela in tabelas
            }
            for futuro in as_completed(futuros):
                tabela_original = futuros[futuro]
                resultado = futuro.result()
                if isinstance(resultado, Falha):
                    identificador = (
                        f"{tabela_original.nome_schema}."
                        f"{tabela_original.nome_tabela}"
                    )
                    falhas.append((identificador, resultado.erro))
                    continue
                tabelas_curadas.append(resultado.valor)

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

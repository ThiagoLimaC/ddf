"""Helper agnóstico de fonte pra montar referências de FK a partir de linhas cruas."""

from collections.abc import Iterable

from ddf.domain.model.common.referencia_de_coluna import ReferenciaDeColuna
from ddf.domain.shared.aviso import Aviso


def construir_colunas_fk(
    linhas_fk: Iterable[tuple[str, str, str, str]], origem: str
) -> tuple[dict[str, ReferenciaDeColuna], list[Aviso]]:
    """Monta o dict coluna→referência de FK, emitindo Aviso em colisão.

    ColunaExtraida.referencia é singular por design — uma coluna com mais de
    uma constraint FK (modelagem polimórfica rara, mas válida no motor)
    mantém só a última referência lida. Em vez de sobrescrever em silêncio,
    emite um Aviso não-fatal nomeando qual referência foi descartada.

    Args:
        linhas_fk: linhas cruas (nome_coluna, escopo_referenciado,
            tabela_referenciada, coluna_referenciada) retornadas pela query
            de FK do Extrator concreto.
        origem: nome do Extrator concreto, usado em Aviso.origem.
    """
    colunas_fk: dict[str, ReferenciaDeColuna] = {}
    avisos: list[Aviso] = []
    for (
        nome_coluna_fk,
        escopo_referenciado,
        tabela_referenciada,
        coluna_referenciada,
    ) in linhas_fk:
        if nome_coluna_fk in colunas_fk:
            anterior = colunas_fk[nome_coluna_fk]
            avisos.append(
                Aviso(
                    mensagem=(
                        f"Coluna '{nome_coluna_fk}' tem mais de uma FK — "
                        f"descartando referência a '{anterior.nome_escopo}."
                        f"{anterior.nome_tabela}.{anterior.nome_coluna}', "
                        f"mantendo '{escopo_referenciado}.{tabela_referenciada}"
                        f".{coluna_referenciada}'."
                    ),
                    origem=origem,
                )
            )
        colunas_fk[nome_coluna_fk] = ReferenciaDeColuna(
            nome_escopo=escopo_referenciado,
            nome_tabela=tabela_referenciada,
            nome_coluna=coluna_referenciada,
        )
    return colunas_fk, avisos

"""Cast/render de SQL e convenção de nomenclatura de model do GeradorDbt."""

from ddf.domain.model.analysis import ColunaAnalisada, TabelaAnalisada
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.infrastructure.adapters.generators.dbt._templates import _TEMPLATE_SQL

_CATEGORIAS_COM_TIMEZONE = {CategoriaDeDado.TIMESTAMP, CategoriaDeDado.TIME}
_CATEGORIAS_SEM_EQUIVALENTE_ANSI = {CategoriaDeDado.ENUM, CategoriaDeDado.SET}


def _nome_model(escopo: str, tabela: str) -> str:
    """Nome do staging model: `stg_<escopo>__<tabela>` (convenção dbt multi-source).

    Única fonte da convenção de nomenclatura — usada tanto para o model que
    a própria tabela gera quanto para o `ref()` de uma FK que aponta para
    outra tabela do lote, evitando duas formatações divergentes do mesmo
    nome.

    Args:
        escopo: `nome_escopo` da tabela.
        tabela: `nome_tabela` da tabela.

    Returns:
        Nome do model, único mesmo quando dois escopos têm tabela de mesmo
        nome — `stg_<tabela>` sozinho colidiria nesse caso.
    """
    return f"stg_{escopo}__{tabela}"


def _tipo_sql(tipo: TipoDeDado) -> str:
    """Mapeia TipoDeDado para o tipo SQL ANSI-ish usado no CAST.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        Tipo SQL com atributos de precisão, ex.: `NUMERIC(10,2)`,
        `VARCHAR(255)`, `TIMESTAMP WITH TIME ZONE`. ENUM/SET (sem
        equivalente ANSI portável) caem para `VARCHAR`.
    """
    categoria = tipo.categoria

    if categoria == CategoriaDeDado.VARCHAR:
        return f"VARCHAR({tipo.tamanho_maximo})" if tipo.tamanho_maximo else "VARCHAR"
    if categoria == CategoriaDeDado.CHAR:
        return f"CHAR({tipo.tamanho_fixo})" if tipo.tamanho_fixo else "CHAR"
    if categoria == CategoriaDeDado.NUMERIC:
        if tipo.precisao is not None:
            return f"NUMERIC({tipo.precisao},{tipo.escala or 0})"
        return "NUMERIC"
    if categoria == CategoriaDeDado.FLOAT:
        return "DOUBLE PRECISION" if tipo.com_precisao_dupla else "REAL"
    if categoria in _CATEGORIAS_COM_TIMEZONE and tipo.com_timezone:
        return f"{categoria.value} WITH TIME ZONE"
    if categoria in _CATEGORIAS_SEM_EQUIVALENTE_ANSI:
        return "VARCHAR"
    if categoria == CategoriaDeDado.ARRAY and tipo.elemento is not None:
        return f"{_tipo_sql(TipoDeDado(categoria=tipo.elemento))}[]"

    return str(categoria.value)


def _tem_cast_seguro(tipo: TipoDeDado) -> bool:
    """Decide se `tipo` tem um CAST SQL seguro a fazer.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        False para UNKNOWN (sem tipo mapeado) e para ARRAY sem elemento
        reconhecido (`[]` sem tipo dentro não é SQL válido) — nesses casos
        a coluna é projetada raw. True para as demais categorias.
    """
    if tipo.categoria == CategoriaDeDado.UNKNOWN:
        return False
    return tipo.categoria != CategoriaDeDado.ARRAY or tipo.elemento is not None


def _expressao_coluna(coluna: ColunaAnalisada) -> str:
    """Monta a expressão SELECT de uma coluna: CAST explícito ou passthrough.

    Args:
        coluna: coluna analisada a projetar no SELECT.

    Returns:
        `CAST(<coluna> AS <tipo>)`, ou o nome puro da coluna quando não há
        CAST seguro a fazer (ver `_tem_cast_seguro`).
    """
    if not _tem_cast_seguro(coluna.tipo_dado):
        return coluna.nome
    return f"CAST({coluna.nome} AS {_tipo_sql(coluna.tipo_dado)})"


def _renderizar_sql(tabela: TabelaAnalisada) -> str:
    """Renderiza o SELECT com CAST + alias por coluna do staging model.

    Args:
        tabela: tabela analisada a projetar.

    Returns:
        SQL do staging model, lendo de `{{ source(escopo, tabela) }}`.
    """
    total = len(tabela.colunas)
    colunas = [
        {
            "expressao": _expressao_coluna(coluna),
            "nome": coluna.nome,
            "sufixo": "," if indice < total - 1 else "",
        }
        for indice, coluna in enumerate(tabela.colunas)
    ]
    origem = "{{ source('" + tabela.nome_escopo + "', '" + tabela.nome_tabela + "') }}"
    return _TEMPLATE_SQL.render(colunas=colunas, origem=origem)

"""Cast/render de SQL e convenção de nomenclatura de model do GeradorDbt."""

from ddf.domain.model.analysis import ColunaAnalisada, TabelaAnalisada
from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado
from ddf.infrastructure.adapters.generators.dbt._templates import _TEMPLATE_SQL

_CATEGORIAS_COM_TIMEZONE = {CategoriaDeDado.TIMESTAMP, CategoriaDeDado.TIME}
_CATEGORIAS_SEM_EQUIVALENTE_ANSI = {CategoriaDeDado.ENUM, CategoriaDeDado.SET}

# Tipos canônicos cujo CAST() não é portável entre Postgres e MariaDB sem
# tradução por adapter — roteados pelo macro dbt `cast_type` (dispatch, um
# arquivo por engine em templates/macros/cast_type/) em vez de CAST literal.
# Validado empiricamente contra os dois motores (ver
# plan/registry-plan/fase-9-fechamento-da-v1/issue-140-*.md).
_CATEGORIAS_DISPATCHADAS = {
    "BIGINT",
    "TEXT",
    "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE",
    "TIME",
    "TIME WITH TIME ZONE",
    "BOOLEAN",
    "JSON",
    "DOUBLE PRECISION",
    "REAL",
    "NUMERIC",
}


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
    """Mapeia TipoDeDado para o tipo SQL canônico usado no CAST.

    Args:
        tipo: tipo de dado da coluna.

    Returns:
        Tipo SQL com atributos de precisão, ex.: `DECIMAL(10,2)`,
        `VARCHAR(255)`, `TIMESTAMP WITH TIME ZONE`. Para as categorias
        listadas em `_CATEGORIAS_DISPATCHADAS`, o literal devolvido não vira
        `CAST()` direto — é o `tipo_canonico` passado ao dispatch
        `cast_type` (ver `_expressao_coluna`), porque `CAST()` do MariaDB
        não aceita esses nomes como destino sem tradução. `VARCHAR` sem
        tamanho (unbounded) e `ENUM`/`SET` (sem equivalente ANSI) convergem
        para o mesmo canônico `TEXT` de um `TEXT` nativo — mesmo risco de
        CAST, mesma tradução.
    """
    categoria = tipo.categoria

    if categoria == CategoriaDeDado.VARCHAR:
        if tipo.tamanho_maximo:
            return f"VARCHAR({tipo.tamanho_maximo})"
        return "TEXT"
    if categoria == CategoriaDeDado.CHAR:
        return f"CHAR({tipo.tamanho_fixo})" if tipo.tamanho_fixo else "CHAR"
    if categoria == CategoriaDeDado.NUMERIC:
        if tipo.precisao is not None:
            return f"DECIMAL({tipo.precisao},{tipo.escala or 0})"
        return "NUMERIC"
    if categoria == CategoriaDeDado.FLOAT:
        return "DOUBLE PRECISION" if tipo.com_precisao_dupla else "REAL"
    if categoria in _CATEGORIAS_COM_TIMEZONE and tipo.com_timezone:
        return f"{categoria.value} WITH TIME ZONE"
    if categoria in _CATEGORIAS_SEM_EQUIVALENTE_ANSI:
        return "TEXT"
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
        `CAST(<coluna> AS <tipo>)` para tipos já portáveis entre Postgres e
        MariaDB; uma chamada ao macro dbt `cast_type(...)` — texto literal,
        interpretado só pelo Jinja do dbt em tempo de `dbt compile`, nunca
        pelo Jinja do `ddf` — para as categorias em
        `_CATEGORIAS_DISPATCHADAS`; ou o nome puro da coluna quando não há
        CAST seguro a fazer (ver `_tem_cast_seguro`).
    """
    if not _tem_cast_seguro(coluna.tipo_dado):
        return coluna.nome
    tipo_canonico = _tipo_sql(coluna.tipo_dado)
    if tipo_canonico in _CATEGORIAS_DISPATCHADAS:
        precisao_fracionaria = coluna.tipo_dado.precisao_fracionaria
        argumentos = f"'{coluna.nome}', '{tipo_canonico}'"
        if precisao_fracionaria is not None:
            argumentos += f", {precisao_fracionaria}"
        return f"{{{{ cast_type({argumentos}) }}}}"
    return f"CAST({coluna.nome} AS {tipo_canonico})"


def _precisa_cast_type(tabelas: list[TabelaAnalisada]) -> bool:
    """Indica se algum consumidor real de `macros/cast_type/` existe no lote.

    Args:
        tabelas: tabelas do lote analisado.

    Returns:
        True se pelo menos uma coluna tem tipo canônico em
        `_CATEGORIAS_DISPATCHADAS` — escrever os macros sem isso seria
        decoração no artefato gerado, mesmo critério dos demais macros
        condicionais do `GeradorDbt`.
    """
    for tabela in tabelas:
        for coluna in tabela.colunas:
            if not _tem_cast_seguro(coluna.tipo_dado):
                continue
            if _tipo_sql(coluna.tipo_dado) in _CATEGORIAS_DISPATCHADAS:
                return True
    return False


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

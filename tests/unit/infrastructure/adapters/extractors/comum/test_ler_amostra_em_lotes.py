"""Testes de calcular_tamanho_lote e ler_amostra_em_lotes."""


from ddf.infrastructure.adapters.extractors.comum.ler_amostra_em_lotes import (
    calcular_tamanho_lote,
    ler_amostra_em_lotes,
)


class _CursorFake:
    """Cursor fake só com `fetchmany`/`description`, devolvendo lotes pré-definidos.

    `description` só populado sob demanda (via `descricao_disponivel`),
    simulando o cursor nomeado do psycopg2 — não disponível antes do 1º
    `fetchmany` (achado real contra Postgres via testcontainers).
    """

    def __init__(
        self,
        lotes: list[list[tuple[object, ...]]],
        nomes_colunas: list[str],
        descricao_disponivel_de_inicio: bool = False,
    ) -> None:
        self._lotes = list(lotes)
        self._nomes_colunas = nomes_colunas
        self._descricao_disponivel = descricao_disponivel_de_inicio

    @property
    def description(self) -> list[tuple[str]] | None:
        if not self._descricao_disponivel:
            return None
        return [(nome,) for nome in self._nomes_colunas]

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self._descricao_disponivel = True
        if not self._lotes:
            return []
        return self._lotes.pop(0)


class TestFeliz:
    """Caminho feliz."""

    def test_divide_teto_de_bytes_pela_largura_media(self) -> None:
        """1000 bytes/lote, linha de 100 bytes -> 10 linhas por lote."""
        tamanho = calcular_tamanho_lote(
            largura_media_bytes=100, teto_bytes=1_000, minimo=1, maximo=1_000
        )

        assert tamanho == 10

    def test_concatena_lotes_ate_fetchmany_devolver_vazio(self) -> None:
        """Dois lotes de 2 linhas cada viram um DataFrame de 4 linhas."""
        cursor = _CursorFake(
            [[(1, "a"), (2, "b")], [(3, "c"), (4, "d")]], nomes_colunas=["id", "valor"]
        )

        amostra = ler_amostra_em_lotes(cursor, tamanho_lote=2)

        assert amostra.to_dicts() == [
            {"id": 1, "valor": "a"},
            {"id": 2, "valor": "b"},
            {"id": 3, "valor": "c"},
            {"id": 4, "valor": "d"},
        ]

    def test_nomes_de_coluna_so_sao_lidos_depois_do_primeiro_fetch(self) -> None:
        """`description` indisponível antes do 1º fetch não quebra a leitura.

        Reproduz o achado real contra Postgres (cursor nomeado só popula
        `description` depois do 1º `fetchmany`) com um cursor fake que
        simula exatamente essa lacuna.
        """
        cursor = _CursorFake(
            [[(1, "a")]],
            nomes_colunas=["id", "valor"],
            descricao_disponivel_de_inicio=False,
        )

        amostra = ler_amostra_em_lotes(cursor, tamanho_lote=10)

        assert amostra.columns == ["id", "valor"]


class TestBorda:
    """Casos de borda."""

    def test_tabela_muito_larga_respeita_minimo(self) -> None:
        """Largura tão grande que o cálculo bruto cairia abaixo do piso."""
        tamanho = calcular_tamanho_lote(
            largura_media_bytes=1_000_000,
            teto_bytes=1_000,
            minimo=50,
            maximo=1_000,
        )

        assert tamanho == 50

    def test_tabela_muito_estreita_respeita_maximo(self) -> None:
        """Largura tão pequena que o cálculo bruto estouraria o teto."""
        tamanho = calcular_tamanho_lote(
            largura_media_bytes=1, teto_bytes=1_000_000, minimo=1, maximo=5_000
        )

        assert tamanho == 5_000

    def test_largura_media_zero_nao_divide_por_zero(self) -> None:
        """largura_media_bytes=0 (catálogo degenerado) não deve estourar."""
        tamanho = calcular_tamanho_lote(
            largura_media_bytes=0, teto_bytes=1_000, minimo=1, maximo=1_000
        )

        assert tamanho == 1_000

    def test_zero_lotes_devolve_dataframe_vazio_com_schema(self) -> None:
        """`fetchmany` já devolvendo vazio na 1ª chamada (tabela sem linhas).

        `description` disponível desde o início: driver real (pymysql)
        popula a descrição de coluna assim que o `execute()` roda, mesmo
        sem nenhuma linha — só o cursor nomeado do psycopg2 tem a lacuna
        coberta pelo outro teste de borda acima.
        """
        cursor = _CursorFake(
            [], nomes_colunas=["id", "valor"], descricao_disponivel_de_inicio=True
        )

        amostra = ler_amostra_em_lotes(cursor, tamanho_lote=100)

        assert amostra.is_empty()
        assert amostra.schema.names() == ["id", "valor"]

    def test_ultimo_lote_parcial_e_incluido(self) -> None:
        """Lote final menor que `tamanho_lote` ainda entra na amostra."""
        cursor = _CursorFake(
            [[(1, "a"), (2, "b")], [(3, "c")]], nomes_colunas=["id", "valor"]
        )

        amostra = ler_amostra_em_lotes(cursor, tamanho_lote=2)

        assert len(amostra) == 3

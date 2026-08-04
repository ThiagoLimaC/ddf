"""Testes de calcular_tamanho_lote e ler_amostra_em_lotes."""


from ddf.infrastructure.adapters.extractors.comum.ler_amostra_em_lotes import (
    calcular_tamanho_lote,
    ler_amostra_em_lotes,
)


class _CursorFake:
    """Cursor fake só com `fetchmany`, devolvendo lotes pré-definidos em ordem."""

    def __init__(self, lotes: list[list[tuple[object, ...]]]) -> None:
        self._lotes = list(lotes)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
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
        cursor = _CursorFake([[(1, "a"), (2, "b")], [(3, "c"), (4, "d")]])

        amostra = ler_amostra_em_lotes(
            cursor, nomes_colunas=["id", "valor"], tamanho_lote=2
        )

        assert amostra.to_dicts() == [
            {"id": 1, "valor": "a"},
            {"id": 2, "valor": "b"},
            {"id": 3, "valor": "c"},
            {"id": 4, "valor": "d"},
        ]


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
        """`fetchmany` já devolvendo vazio na 1ª chamada (tabela sem linhas)."""
        cursor = _CursorFake([])

        amostra = ler_amostra_em_lotes(
            cursor, nomes_colunas=["id", "valor"], tamanho_lote=100
        )

        assert amostra.is_empty()
        assert amostra.schema.names() == ["id", "valor"]

    def test_ultimo_lote_parcial_e_incluido(self) -> None:
        """Lote final menor que `tamanho_lote` ainda entra na amostra."""
        cursor = _CursorFake([[(1, "a"), (2, "b")], [(3, "c")]])

        amostra = ler_amostra_em_lotes(
            cursor, nomes_colunas=["id", "valor"], tamanho_lote=2
        )

        assert len(amostra) == 3

"""Testes diretos das funções puras de _construcao.py.

As demais funções deste módulo (_construir_coluna,
_promover_booleanos_pela_amostra, _particionar_colunas_unicas,
_agrupar_colunas_unicas_por_tabela, _colunas_json_de_check_clauses,
_agrupar_colunas_json_por_tabela) já têm cobertura substancial e realista via
ExtratorMariaDB.extrair_tabela em test_extrator_mariadb.py — este arquivo
cobre só o que não tinha nenhum teste, direto ou indireto, antes do split.
"""

from ddf.infrastructure.adapters.extractors.mariadb._construcao import (
    _quotar_identificador,
)


class TestBorda:
    """Bordas."""

    def test_identificador_com_crase_e_escapado_com_crase_duplicada(self) -> None:
        """Crase literal no nome vira crase duplicada, sem quebrar o SQL."""
        assert _quotar_identificador("tabela`maliciosa") == "`tabela``maliciosa`"

    def test_identificador_sem_caractere_especial_so_e_envolto_em_crases(
        self,
    ) -> None:
        """Nome comum não sofre nenhuma substituição, só recebe as crases."""
        assert _quotar_identificador("clientes") == "`clientes`"

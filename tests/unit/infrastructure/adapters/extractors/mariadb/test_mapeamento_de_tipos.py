"""Testes de mapear_tipo_mariadb e _extrair_coluna_json_valid."""

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado
from ddf.infrastructure.adapters.extractors.mariadb.mapeamento_de_tipos import (
    _extrair_coluna_json_valid,
    mapear_tipo_mariadb,
)


class TestFeliz:
    """Caminho feliz."""

    def test_mapeia_varchar_com_tamanho_maximo(
        self,
    ) -> None:
        """varchar(n) vira VARCHAR com tamanho_maximo."""
        tipo = mapear_tipo_mariadb("varchar", "varchar(255)", tamanho_maximo=255)

        assert tipo.categoria == CategoriaDeDado.VARCHAR
        assert tipo.tamanho_maximo == 255

    def test_mapeia_char_com_tamanho_fixo(
        self,
    ) -> None:
        """char(n) vira CHAR com tamanho_fixo."""
        tipo = mapear_tipo_mariadb("char", "char(10)", tamanho_maximo=10)

        assert tipo.categoria == CategoriaDeDado.CHAR
        assert tipo.tamanho_fixo == 10

    def test_mapeia_variantes_de_text_para_text(
        self,
    ) -> None:
        """tinytext/text/mediumtext/longtext compartilham TEXT."""
        for data_type in ("tinytext", "text", "mediumtext", "longtext"):
            assert (
                mapear_tipo_mariadb(data_type, data_type).categoria
                == CategoriaDeDado.TEXT
            )

    def test_mapeia_decimal_para_numeric_com_precisao_e_escala(
        self,
    ) -> None:
        """decimal(p,s) vira NUMERIC com precisao e escala."""
        tipo = mapear_tipo_mariadb("decimal", "decimal(10,2)", precisao=10, escala=2)

        assert tipo.categoria == CategoriaDeDado.NUMERIC
        assert tipo.precisao == 10
        assert tipo.escala == 2

    def test_mapeia_variantes_de_int_para_integer(
        self,
    ) -> None:
        """tinyint/smallint/mediumint/int compartilham INTEGER."""
        for data_type, column_type in (
            ("tinyint", "tinyint(1)"),
            ("tinyint", "tinyint(4)"),
            ("smallint", "smallint(6)"),
            ("mediumint", "mediumint(9)"),
            ("int", "int(11)"),
        ):
            assert (
                mapear_tipo_mariadb(data_type, column_type).categoria
                == CategoriaDeDado.INTEGER
            )

    def test_mapeia_bigint_para_bigint(
        self,
    ) -> None:
        """Bigint vira BIGINT."""
        assert (
            mapear_tipo_mariadb("bigint", "bigint(20)").categoria
            == CategoriaDeDado.BIGINT
        )

    def test_mapeia_float_e_double_com_precisao_dupla(
        self,
    ) -> None:
        """float/double compartilham FLOAT, variam em largura."""
        float_ = mapear_tipo_mariadb("float", "float")
        double = mapear_tipo_mariadb("double", "double")

        assert float_.categoria == CategoriaDeDado.FLOAT
        assert float_.com_precisao_dupla is False
        assert double.categoria == CategoriaDeDado.FLOAT
        assert double.com_precisao_dupla is True

    def test_mapeia_datetime_e_timestamp_com_timezone(
        self,
    ) -> None:
        """datetime/timestamp viram TIMESTAMP com com_timezone distinto."""
        datetime_ = mapear_tipo_mariadb("datetime", "datetime")
        timestamp = mapear_tipo_mariadb("timestamp", "timestamp")

        assert datetime_.categoria == CategoriaDeDado.TIMESTAMP
        assert datetime_.com_timezone is False
        assert timestamp.categoria == CategoriaDeDado.TIMESTAMP
        assert timestamp.com_timezone is True

    def test_mapeia_date_para_date(
        self,
    ) -> None:
        """Date vira DATE."""
        assert mapear_tipo_mariadb("date", "date").categoria == CategoriaDeDado.DATE

    def test_mapeia_time_para_time(
        self,
    ) -> None:
        """Time vira TIME."""
        assert mapear_tipo_mariadb("time", "time").categoria == CategoriaDeDado.TIME

    def test_mapeia_precisao_fracionaria_para_datetime_timestamp_e_time(
        self,
    ) -> None:
        """datetime_precision propaga pra TipoDeDado.precisao_fracionaria."""
        datetime_ = mapear_tipo_mariadb(
            "datetime", "datetime(3)", precisao_fracionaria=3
        )
        timestamp = mapear_tipo_mariadb(
            "timestamp", "timestamp(6)", precisao_fracionaria=6
        )
        time = mapear_tipo_mariadb("time", "time(2)", precisao_fracionaria=2)

        assert datetime_.precisao_fracionaria == 3
        assert timestamp.precisao_fracionaria == 6
        assert time.precisao_fracionaria == 2

    def test_extrai_coluna_de_check_clause_json_valid(
        self,
    ) -> None:
        """json_valid(`col`) extrai o nome da coluna.

        Formato exato validado empiricamente contra MariaDB 11 real (issue
        #56) — mesmo CHECK_CLAUSE para coluna `JSON` nativa e para
        `CHECK(JSON_VALID(...))` explícito, sempre normalizado para minúsculas.
        """
        assert _extrair_coluna_json_valid("json_valid(`dados`)") == "dados"

    def test_extrai_coluna_de_check_clause_json_valid_case_insensitive(
        self,
    ) -> None:
        """Reconhece JSON_VALID em maiúsculas, defensivamente.

        MariaDB 11 real sempre normaliza para minúsculas (validado empiricamente)
        — este caso cobre a robustez do regex, não um comportamento observado.
        """
        assert _extrair_coluna_json_valid("JSON_VALID(`dados`)") == "dados"

    def test_mapeia_uuid_para_uuid(
        self,
    ) -> None:
        """Uuid (MariaDB 10.7+) vira UUID."""
        assert mapear_tipo_mariadb("uuid", "uuid").categoria == CategoriaDeDado.UUID

    def test_mapeia_enum_com_valores_permitidos(
        self,
    ) -> None:
        """enum(...) vira ENUM com valores_permitidos extraídos."""
        tipo = mapear_tipo_mariadb("enum", "enum('ativo','inativo')")

        assert tipo.categoria == CategoriaDeDado.ENUM
        assert tipo.valores_permitidos == ("ativo", "inativo")

    def test_mapeia_set_com_valores_permitidos(
        self,
    ) -> None:
        """set(...) vira SET com valores_permitidos extraídos."""
        tipo = mapear_tipo_mariadb("set", "set('leitura','escrita')")

        assert tipo.categoria == CategoriaDeDado.SET
        assert tipo.valores_permitidos == ("leitura", "escrita")

    def test_tinyint_um_nunca_vira_boolean(
        self,
    ) -> None:
        """tinyint(1) vira INTEGER nesta função — nunca BOOLEAN.

        A promoção pra BOOLEAN depende da amostra real, feita por
        ExtratorMariaDB — mapear_tipo_mariadb é função pura só de metadado.
        """
        assert (
            mapear_tipo_mariadb("tinyint", "tinyint(1)").categoria
            == CategoriaDeDado.INTEGER
        )


class TestBorda:
    """Bordas."""

    def test_valor_de_enum_com_aspa_escapada(
        self,
    ) -> None:
        """Valor de enum contendo aspa literal escapada (`''`) é desescapado."""
        tipo = mapear_tipo_mariadb("enum", "enum('a''b','c')")

        assert tipo.valores_permitidos == ("a'b", "c")

    def test_tipo_desconhecido_vira_unknown(
        self,
    ) -> None:
        """Tipo fora da tabela de mapeamento vira UNKNOWN, sem exceção."""
        assert mapear_tipo_mariadb("blob", "blob").categoria == CategoriaDeDado.UNKNOWN
        assert mapear_tipo_mariadb("bit", "bit(1)").categoria == CategoriaDeDado.UNKNOWN

    def test_data_type_json_isolado_vira_unknown(
        self,
    ) -> None:
        """data_type == "json" sozinho (sem CHECK_CLAUSE) vira UNKNOWN.

        Documenta a decisão da issue #56: contra um MariaDB real, data_type
        nunca é "json" — a reclassificação correta depende de
        _extrair_coluna_json_valid sobre o CHECK_CLAUSE, feita por
        ExtratorMariaDB, não desta função pura.
        """
        assert (
            mapear_tipo_mariadb("json", "longtext").categoria == CategoriaDeDado.UNKNOWN
        )

    def test_check_clause_nao_relacionado_a_json_retorna_none(
        self,
    ) -> None:
        """CHECK_CLAUSE de uma constraint comum (não JSON) não casa o padrão."""
        assert _extrair_coluna_json_valid("`idade` >= 0") is None

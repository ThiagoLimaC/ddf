"""Testes de TipoDeDado."""

import pytest
from pydantic import ValidationError

from ddf.domain.model.common.tipo_de_dado import CategoriaDeDado, TipoDeDado


class TestFeliz:
    """Caminho feliz."""

    def test_cria_tipo_numeric_com_precisao_e_escala(self) -> None:
        """TipoDeDado NUMERIC guarda precisao e escala."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10, escala=2)

        assert tipo.categoria == CategoriaDeDado.NUMERIC
        assert tipo.precisao == 10
        assert tipo.escala == 2

    def test_cria_tipo_float_com_precisao_dupla(self) -> None:
        """FLOAT distingue real/double precision via com_precisao_dupla."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.FLOAT, com_precisao_dupla=True)

        assert tipo.categoria == CategoriaDeDado.FLOAT
        assert tipo.com_precisao_dupla is True
        assert tipo.precisao is None
        assert tipo.escala is None

    def test_cria_tipo_char_com_tamanho_fixo(self) -> None:
        """CHAR guarda tamanho_fixo, distinto de tamanho_maximo."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_fixo=10)

        assert tipo.categoria == CategoriaDeDado.CHAR
        assert tipo.tamanho_fixo == 10

    def test_cria_tipo_uuid_sem_atributos(self) -> None:
        """UUID não aceita nenhum atributo extra."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.UUID)

        assert tipo.categoria == CategoriaDeDado.UUID

    def test_cria_tipo_timestamp_com_timezone(self) -> None:
        """TIMESTAMP e TIME compartilham o atributo com_timezone."""
        com_tz = TipoDeDado(categoria=CategoriaDeDado.TIMESTAMP, com_timezone=True)
        sem_tz = TipoDeDado(categoria=CategoriaDeDado.TIME, com_timezone=False)

        assert com_tz.com_timezone is True
        assert sem_tz.com_timezone is False

    def test_cria_tipo_timestamp_com_precisao_fracionaria(self) -> None:
        """TIMESTAMP e TIME compartilham o atributo precisao_fracionaria."""
        timestamp = TipoDeDado(
            categoria=CategoriaDeDado.TIMESTAMP, precisao_fracionaria=6
        )
        time = TipoDeDado(categoria=CategoriaDeDado.TIME, precisao_fracionaria=0)

        assert timestamp.precisao_fracionaria == 6
        assert time.precisao_fracionaria == 0

    def test_cria_tipo_enum_com_valores_permitidos(self) -> None:
        """ENUM guarda a lista de valores aceitos."""
        tipo = TipoDeDado(
            categoria=CategoriaDeDado.ENUM, valores_permitidos=("ativo", "inativo")
        )

        assert tipo.categoria == CategoriaDeDado.ENUM
        assert tipo.valores_permitidos == ("ativo", "inativo")

    def test_cria_tipo_set_com_valores_permitidos(self) -> None:
        """SET compartilha o mesmo atributo valores_permitidos do ENUM."""
        tipo = TipoDeDado(
            categoria=CategoriaDeDado.SET, valores_permitidos=("leitura", "escrita")
        )

        assert tipo.categoria == CategoriaDeDado.SET
        assert tipo.valores_permitidos == ("leitura", "escrita")

    def test_cria_tipo_array_com_elemento(self) -> None:
        """ARRAY guarda a categoria do elemento, sem precisão dele."""
        tipo = TipoDeDado(
            categoria=CategoriaDeDado.ARRAY, elemento=CategoriaDeDado.INTEGER
        )

        assert tipo.categoria == CategoriaDeDado.ARRAY
        assert tipo.elemento == CategoriaDeDado.INTEGER


class TestErro:
    """Erro esperado."""

    def test_categoria_invalida_levanta_validation_error(self) -> None:
        """Categoria fora do Enum levanta ValidationError."""
        with pytest.raises(ValidationError):
            TipoDeDado(categoria="POSTGRES_ARRAY")  # type: ignore[arg-type]

    def test_integer_com_tamanho_maximo_levanta_validation_error(self) -> None:
        """Atributo de outra categoria (tamanho_maximo) em INTEGER."""
        with pytest.raises(ValidationError, match="INTEGER"):
            TipoDeDado(categoria=CategoriaDeDado.INTEGER, tamanho_maximo=10)

    def test_varchar_com_precisao_levanta_validation_error(self) -> None:
        """Atributo de NUMERIC (precisao) usado em VARCHAR."""
        with pytest.raises(ValidationError, match="VARCHAR"):
            TipoDeDado(categoria=CategoriaDeDado.VARCHAR, precisao=10)

    def test_numeric_com_tamanho_maximo_levanta_validation_error(self) -> None:
        """Atributo de VARCHAR (tamanho_maximo) usado em NUMERIC."""
        with pytest.raises(ValidationError, match="NUMERIC"):
            TipoDeDado(categoria=CategoriaDeDado.NUMERIC, tamanho_maximo=10)

    def test_numeric_com_escala_sem_precisao_levanta_validation_error(self) -> None:
        """Escala sem precisao é um NUMERIC inconsistente."""
        with pytest.raises(ValidationError, match="escala"):
            TipoDeDado(categoria=CategoriaDeDado.NUMERIC, escala=2)

    def test_float_com_precisao_levanta_validation_error(self) -> None:
        """FLOAT não aceita precisao (não é decimal configurável)."""
        with pytest.raises(ValidationError, match="FLOAT"):
            TipoDeDado(categoria=CategoriaDeDado.FLOAT, precisao=24)

    def test_char_com_tamanho_maximo_levanta_validation_error(self) -> None:
        """CHAR não aceita tamanho_maximo (atributo é de VARCHAR)."""
        with pytest.raises(ValidationError, match="CHAR"):
            TipoDeDado(categoria=CategoriaDeDado.CHAR, tamanho_maximo=10)

    def test_uuid_com_tamanho_fixo_levanta_validation_error(self) -> None:
        """UUID não aceita tamanho_fixo."""
        with pytest.raises(ValidationError, match="UUID"):
            TipoDeDado(categoria=CategoriaDeDado.UUID, tamanho_fixo=36)

    def test_date_com_timezone_levanta_validation_error(self) -> None:
        """com_timezone é exclusivo de TIMESTAMP/TIME, não de DATE."""
        with pytest.raises(ValidationError, match="DATE"):
            TipoDeDado(categoria=CategoriaDeDado.DATE, com_timezone=True)

    def test_numeric_com_precisao_dupla_levanta_validation_error(self) -> None:
        """com_precisao_dupla é exclusivo de FLOAT, não de NUMERIC."""
        with pytest.raises(ValidationError, match="NUMERIC"):
            TipoDeDado(categoria=CategoriaDeDado.NUMERIC, com_precisao_dupla=True)

    def test_date_com_precisao_fracionaria_levanta_validation_error(self) -> None:
        """precisao_fracionaria é exclusivo de TIMESTAMP/TIME, não de DATE."""
        with pytest.raises(ValidationError, match="DATE"):
            TipoDeDado(categoria=CategoriaDeDado.DATE, precisao_fracionaria=3)

    def test_varchar_com_valores_permitidos_levanta_validation_error(self) -> None:
        """valores_permitidos é exclusivo de ENUM/SET, não de VARCHAR."""
        with pytest.raises(ValidationError, match="VARCHAR"):
            TipoDeDado(categoria=CategoriaDeDado.VARCHAR, valores_permitidos=("a",))

    def test_varchar_com_elemento_levanta_validation_error(self) -> None:
        """Elemento é exclusivo de ARRAY, não de VARCHAR."""
        with pytest.raises(ValidationError, match="VARCHAR"):
            TipoDeDado(categoria=CategoriaDeDado.VARCHAR, elemento=CategoriaDeDado.TEXT)


class TestBorda:
    """Bordas."""

    def test_categoria_unknown_nao_levanta_excecao(self) -> None:
        """UNKNOWN é aceito sem atributos extras, sem exceção por tipo raro."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.UNKNOWN)

        assert tipo.categoria == CategoriaDeDado.UNKNOWN
        assert tipo.precisao is None
        assert tipo.escala is None
        assert tipo.tamanho_maximo is None

    def test_tipo_de_dado_e_imutavel(self, tipo_varchar: TipoDeDado) -> None:
        """TipoDeDado é imutável após construção (frozen=True via ConfigDict)."""
        with pytest.raises(ValidationError):
            tipo_varchar.tamanho_maximo = 500

    def test_numeric_apenas_com_precisao_e_aceito(self) -> None:
        """NUMERIC aceita só precisao preenchida, sem escala."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.NUMERIC, precisao=10)

        assert tipo.precisao == 10
        assert tipo.escala is None

    def test_array_sem_elemento_e_aceito(self) -> None:
        """ARRAY sem elemento reconhecido é aceito (elemento fora do mapeamento)."""
        tipo = TipoDeDado(categoria=CategoriaDeDado.ARRAY)

        assert tipo.categoria == CategoriaDeDado.ARRAY
        assert tipo.elemento is None

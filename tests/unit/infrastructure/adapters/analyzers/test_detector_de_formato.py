"""Testes de detectar_formato."""

from ddf.infrastructure.adapters.analyzers.detector_de_formato import detectar_formato

# Caminho feliz


def test_detecta_email_com_subdominio_e_tld_composto() -> None:
    r"""Caminho feliz: e-mails com subdomínio/TLD composto são detectados.

    Regressão do achado da banca de revisão: a regex original
    (`[\w-]+\.[a-z]{2,}`) tinha falso negativo em domínios como
    'empresa.com.br', o caso mais comum em bases brasileiras reais.
    """
    valores = [f"user{i}@mail.empresa.com.br" for i in range(20)]

    assert detectar_formato(valores) == "email"


def test_detecta_email_maiusculo() -> None:
    """Caminho feliz: TLD/domínio em maiúsculo também é detectado (re.IGNORECASE)."""
    valores = [f"USER{i}@EMPRESA.COM" for i in range(20)]

    assert detectar_formato(valores) == "email"


def test_detecta_cnpj() -> None:
    """Caminho feliz: CNPJs formatados são detectados."""
    valores = ["12.345.678/0001-90" for _ in range(20)]

    assert detectar_formato(valores) == "cnpj"


def test_detecta_cep() -> None:
    """Caminho feliz: CEPs formatados são detectados."""
    valores = ["01310-100" for _ in range(20)]

    assert detectar_formato(valores) == "cep"


def test_precedencia_quando_valor_bate_mais_de_um_regex() -> None:
    """Caminho feliz: '12345678901' bate cpf e phone; cpf vence por precedência."""
    valores = ["12345678901" for _ in range(20)]

    assert detectar_formato(valores) == "cpf"


# Borda


def test_nenhum_formato_detectado_abaixo_do_threshold() -> None:
    """Borda: só 50% dos valores são e-mail, abaixo do threshold de 80%."""
    valores = [f"user{i}@empresa.com" for i in range(10)] + [
        f"texto livre {i}" for i in range(10)
    ]

    assert detectar_formato(valores) is None


def test_nenhum_formato_detectado_com_menos_de_20_valores() -> None:
    """Borda: 100% de match, mas só 19 valores não atinge o mínimo absoluto."""
    valores = [f"user{i}@empresa.com" for i in range(19)]

    assert detectar_formato(valores) is None


def test_lista_vazia_nao_detecta_formato() -> None:
    """Borda: lista vazia não deve levantar erro, só retornar None."""
    assert detectar_formato([]) is None

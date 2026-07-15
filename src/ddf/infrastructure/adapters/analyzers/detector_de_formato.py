"""Detecção heurística de formato de valores VARCHAR/TEXT via regex."""

import re

_REGEXES: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"^[\w.+-]+@[\w.-]+\.[a-z]{2,}$", re.IGNORECASE),
    "cpf": re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"),
    "cnpj": re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"),
    "phone": re.compile(r"^(\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}$"),
    "cep": re.compile(r"^\d{5}-?\d{3}$"),
}
"""Ordem = precedência: primeiro formato que atinge o threshold vence."""

_THRESHOLD = 0.8
_MINIMO_NAO_NULOS = 20


def detectar_formato(valores: list[str]) -> str | None:
    """Detecta o formato dominante entre os valores não-nulos de uma coluna.

    Args:
        valores: valores não-nulos de uma coluna VARCHAR/TEXT.

    Returns:
        Nome do formato ("email"/"cpf"/"cnpj"/"phone"/"cep") cujo regex
        casa pelo menos 80% dos valores, ou None se nenhum atingir o
        threshold ou se houver menos de 20 valores não-nulos.
    """
    if len(valores) < _MINIMO_NAO_NULOS:
        return None

    for formato, regex in _REGEXES.items():
        casados = sum(1 for valor in valores if regex.match(valor))
        if casados / len(valores) >= _THRESHOLD:
            return formato

    return None

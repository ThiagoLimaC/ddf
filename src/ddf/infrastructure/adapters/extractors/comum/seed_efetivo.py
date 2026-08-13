"""Helper agnóstico de fonte pra sempre ter um seed concreto de amostragem."""

_SEED_PADRAO = 142

# Constante global do ddf, não específica de uma extração — todo Extrator
# que não recebe seed explícito do usuário cai na mesma fatia física da
# tabela sempre que reamostra. Isso dá diff estável em Git entre execuções
# (mesma amostra, mesmas linhas, artefato não muda por ruído de amostragem),
# mas não é "amostra aleatória reproduzível eventualmente": é sempre a MESMA
# amostra. Se essa fatia calhar de ser não-representativa da tabela, o viés
# nunca é percebido, porque a amostra nunca varia entre execuções pra expor
# a diferença. Rotação ocasional é responsabilidade do usuário, via seed
# explícito — ver docs/system_design_doc.md, seção MetadadosDeAmostra.


def seed_efetivo(seed: int | None) -> int:
    """Devolve `seed` se informado, senão o seed default fixo do ddf.

    Args:
        seed: valor informado pelo usuário, ou None se não informado.
    """
    if seed is not None:
        return seed
    return _SEED_PADRAO

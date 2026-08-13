"""Etapas 1-5 do wizard: conexão, escopos, amostragem e extração das tabelas."""

import sys
import time

from ddf.domain.model.common.configuracao_de_extracao import ConfiguracaoDeExtracao
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.ports.extrator import Extrator
from ddf.domain.ports.orquestrador_de_tabelas import OrquestradorDeTabelas
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha
from ddf.infrastructure.adapters.cli import prompts
from ddf.infrastructure.adapters.cli.avisos import exibir_avisos, ou_sair
from ddf.infrastructure.adapters.cli.registro.estrategias import (
    ESTRATEGIAS_REGISTRADAS,
)
from ddf.infrastructure.adapters.cli.registro.extratores import (
    EXTRATORES_REGISTRADOS,
)

_MAXIMO_TENTATIVAS_CONEXAO = 3
_ORIGEM = "Extracao"


def conectar() -> tuple[Extrator, ConfiguracaoDeExtracao, list[str]]:
    """Etapas 1-2: escolhe a fonte, constrói o Extrator sem estratégia, testa conexão.

    A estratégia de amostragem só é escolhida depois, em
    `configurar_amostragem` — já com fonte conectada e escopos conhecidos —
    por isso `ConfiguracaoDeExtracao` é construída aqui com `estrategia=None`
    e devolvida junto, para ser preenchida antes da extração de fato.

    Reaproveita o Resultado de `listar_escopos()` como sonda de
    conectividade — a etapa 3 (escolher escopos) usa a mesma lista, sem uma
    2ª chamada de rede.
    """
    nome_fonte = prompts.selecionar("Qual fonte?", list(EXTRATORES_REGISTRADOS.keys()))
    configuracao = ConfiguracaoDeExtracao()
    extrator, escopos = _testar_conexao(nome_fonte, configuracao)
    return extrator, configuracao, escopos


def configurar_amostragem(configuracao: ConfiguracaoDeExtracao) -> None:
    """Etapa 4: escolhe a estratégia de amostragem, atribuindo à configuração já em uso.

    `configuracao` é o mesmo objeto já guardado pelo Extrator construído em
    `conectar` — atribuir `estrategia` aqui é o que ele lê ao extrair.

    `EstrategiaDeAmostragem` é um Port — `PercentualDeLinhas` e
    `TabelaInteira` já provam que o registro cresce sem precisar editar
    este wizard.
    """
    nome_estrategia = prompts.selecionar(
        "Qual estratégia de amostragem?", list(ESTRATEGIAS_REGISTRADAS.keys())
    )
    configuracao.estrategia = ESTRATEGIAS_REGISTRADAS[nome_estrategia].construir()


def _testar_conexao(
    nome_fonte: str, configuracao: ConfiguracaoDeExtracao
) -> tuple[Extrator, list[str]]:
    """Etapa 3: constrói o Extrator e testa a conexão, com retry manual até 3x.

    Reconstrói o Extrator a cada tentativa — pedindo host/porta/credenciais
    de novo — em vez de reusar a mesma instância com os mesmos parâmetros já
    errados: se a falha foi por um dado digitado errado (ex.: senha), retry
    cego contra a mesma credencial nunca teria sucesso, só desperdiçaria
    tentativas. Nunca insiste sozinho — quem decide tentar de novo (e o que
    muda nos parâmetros) é o usuário.
    """
    tentativa = 1
    while True:
        extrator = EXTRATORES_REGISTRADOS[nome_fonte].construir(configuracao)
        with prompts.ampulheta("Testando conexão..."):
            resultado = extrator.listar_escopos()
        print()
        if not isinstance(resultado, Falha):
            prompts.imprimir_destacado("✓ Conexão validada.", prompts.COR_SUCESSO)
            return extrator, resultado.valor

        prompts.imprimir_destacado(
            f"Falha ao conectar (tentativa {tentativa}/"
            f"{_MAXIMO_TENTATIVAS_CONEXAO}): {resultado.erro}",
            prompts.COR_ERRO,
        )
        if tentativa >= _MAXIMO_TENTATIVAS_CONEXAO:
            sys.exit(1)
        if not prompts.confirmar("Tentar novamente?"):
            sys.exit(1)
        tentativa += 1


def listar_pares(extrator: Extrator, escopos: list[str]) -> list[tuple[str, str]]:
    """Lista as tabelas dos escopos escolhidos, agregadas em pares (escopo, tabela).

    Falha ao listar um escopo vira Aviso e não impede a listagem dos
    demais — mesma política de sucesso parcial usada no restante do
    wizard.
    """
    pares: list[tuple[str, str]] = []
    avisos_listagem: list[Aviso] = []
    for escopo in escopos:
        resultado = extrator.listar_tabelas(escopo)
        if isinstance(resultado, Falha):
            avisos_listagem.append(
                Aviso(
                    mensagem=(
                        f"Falha ao listar tabelas de '{escopo}': {resultado.erro}"
                    ),
                    origem=_ORIGEM,
                )
            )
            continue
        pares.extend(resultado.valor)
    exibir_avisos(avisos_listagem)
    return pares


def escolher_tabelas(pares_disponiveis: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Etapa opcional: extração completa do escopo ou seleção manual de tabelas.

    "Extração completa" é o default (`confirmar` com `default=False` na
    pergunta de restringir) — quem só aperta Enter mantém o comportamento
    de sempre, sem nunca ver a lista de tabelas. Quem restringe escolhe a
    partir de uma lista vazia (não pré-marcada) e é reperguntado até marcar
    ao menos uma, em vez de o wizard sair em silêncio.
    """
    if not prompts.confirmar("Restringir tabelas extraídas?", default=False):
        return pares_disponiveis

    # "›", não "." — "." é caractere válido em identificador citado do
    # Postgres/MySQL; usá-lo colidiria dois pares distintos no mesmo rótulo
    # (ex.: ("a.b", "c") e ("a", "b.c")) e marcaria os dois juntos.
    rotulos = [f"{escopo} › {tabela}" for escopo, tabela in pares_disponiveis]
    while True:
        rotulos_escolhidos = prompts.escolher_multiplos(
            "Escolha uma ou mais tabelas:", rotulos, permite_vazio=True
        )
        if rotulos_escolhidos:
            break
        prompts.imprimir_destacado(
            "Nenhuma tabela selecionada — marque ao menos uma.", prompts.COR_ERRO
        )

    escolhidos = set(rotulos_escolhidos)
    return [
        par
        for par, rotulo in zip(pares_disponiveis, rotulos, strict=True)
        if rotulo in escolhidos
    ]


def extrair(
    orquestrador: OrquestradorDeTabelas,
    extrator: Extrator,
    pares: list[tuple[str, str]],
) -> list[TabelaExtraida]:
    """Etapa 5: extrai, em paralelo, as tabelas selecionadas.

    O total exibido na barra de progresso já é conhecido de antemão
    (`len(pares)`) — a listagem acontece antes, em `listar_pares`.
    """
    inicio = time.monotonic()
    with prompts.progresso_paralelo("Tabelas extraídas", total=len(pares)) as progresso:
        resultado = orquestrador.extrair(pares, extrator, progresso=progresso)
    print()
    tabelas = ou_sair(resultado)
    prompts.imprimir_destacado(
        f"✓ {len(tabelas)} tabela(s) extraída(s).", prompts.COR_SUCESSO
    )
    print(f"duração: {time.monotonic() - inicio:.0f}s")
    return tabelas

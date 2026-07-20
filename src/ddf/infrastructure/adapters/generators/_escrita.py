"""Escrita em disco compartilhada entre os Geradores."""

from pathlib import Path

from ddf.domain.shared.resultado import Falha, Resultado, Sucesso


def escrever_arquivo(caminho: Path, conteudo: str) -> Resultado[None]:
    """Cria os diretórios pais se necessário e escreve o conteúdo em disco.

    Args:
        caminho: arquivo de destino.
        conteudo: texto a ser escrito.

    Returns:
        Sucesso(None), ou Falha com o path e o detalhe do OSError.
    """
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")
    except OSError as erro:
        return Falha(f"Não foi possível escrever em '{caminho}': {erro}")
    return Sucesso(None)

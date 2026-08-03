"""ACL Extraction → Curation: aplica curadoria humana via arquivos YAML."""

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from ddf.domain.model.curation import ColunaCurada, TabelaCurada
from ddf.domain.model.extraction import TabelaExtraida
from ddf.domain.shared.aviso import Aviso
from ddf.domain.shared.resultado import Falha, Resultado, Sucesso

_ORIGEM = "SobrescritaDeTabela"


class _ColunaSobrescritaYAML(BaseModel):
    """Curadoria de uma coluna, tal como persistida no skeleton YAML."""

    papel_de_negocio: str = ""
    regras_de_negocio: list[str] = Field(default_factory=list)


class _TabelaSobrescritaYAML(BaseModel):
    """Curadoria de uma tabela, tal como persistida no skeleton YAML."""

    hash: str
    papel_de_negocio: str = ""
    regras_de_negocio: list[str] = Field(default_factory=list)
    colunas: dict[str, _ColunaSobrescritaYAML] = Field(default_factory=dict)


def _calcular_hash_estrutural(tabela: TabelaExtraida) -> str:
    """Hash SHA-256 sobre os campos estruturais de uma TabelaExtraida.

    Args:
        tabela: tabela extraída cuja estrutura será resumida em um hash.

    Returns:
        Hash hexadecimal determinístico entre execuções.
    """
    partes: list[str] = [tabela.nome_escopo, tabela.nome_tabela]
    for coluna in tabela.colunas:
        partes.append(coluna.nome)
        partes.append(coluna.tipo_dado.model_dump_json())
        partes.append(str(coluna.chave_primaria))
        partes.append(str(coluna.chave_estrangeira))
        partes.append(str(coluna.nao_nulavel))
        partes.append(str(coluna.unica))
        partes.append(
            "|".join(referencia.model_dump_json() for referencia in coluna.referencias)
        )
    for restricao in tabela.restricoes_unicas:
        partes.append("restricao_unica:" + ",".join(restricao.colunas))
    for restricao_fk in tabela.restricoes_fk_compostas:
        partes.append(
            "restricao_fk_composta:"
            + ",".join(restricao_fk.colunas_locais)
            + "->"
            + restricao_fk.nome_escopo_referenciado
            + "."
            + restricao_fk.nome_tabela_referenciada
            + ":"
            + ",".join(restricao_fk.colunas_referenciadas)
        )
    bruto = "|".join(partes).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


class SobrescritaDeTabela:
    """Traduz TabelaExtraida em TabelaCurada, aplicando curadoria de overrides/*.yaml.

    ACL entre Extraction e Curation — única responsabilidade é produzir uma
    TabelaCurada a partir de uma TabelaExtraida.
    """

    def __init__(self, diretorio_sobrescritas: Path) -> None:
        """Guarda o diretório raiz onde os arquivos de sobrescrita ficam.

        Args:
            diretorio_sobrescritas: diretório raiz de
                `<diretorio_sobrescritas>/<escopo>/<tabela>.yaml`.
        """
        self._diretorio = diretorio_sobrescritas

    def __call__(self, entrada: TabelaExtraida) -> Resultado[TabelaCurada]:
        """Aplica a sobrescrita de curadoria sobre uma TabelaExtraida.

        Args:
            entrada: tabela extraída da fonte, sem curadoria.

        Returns:
            Sucesso com a TabelaCurada (curadoria aplicada, skeleton gerado
            na 1ª execução, ou skeleton atualizado se a estrutura mudou), ou
            Falha se o YAML existente estiver malformado.
        """
        tabela_traduzida = self._traduzir(entrada)
        caminho = self._diretorio / entrada.nome_escopo / f"{entrada.nome_tabela}.yaml"
        hash_atual = _calcular_hash_estrutural(entrada)

        if not caminho.exists():
            return self._gerar_skeleton(entrada, tabela_traduzida, caminho, hash_atual)

        try:
            bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
            override = _TabelaSobrescritaYAML.model_validate(bruto)
        except (yaml.YAMLError, ValidationError) as erro:
            return Falha(
                f"Sobrescrita de '{entrada.nome_escopo}.{entrada.nome_tabela}' "
                f"está malformada: {erro}"
            )

        if override.hash == hash_atual:
            return Sucesso(self._aplicar_curadoria(tabela_traduzida, override))

        return self._atualizar_skeleton(
            entrada, tabela_traduzida, override, caminho, hash_atual
        )

    def _traduzir(self, tabela: TabelaExtraida) -> TabelaCurada:
        """Mapeia estrutura de TabelaExtraida para TabelaCurada, sem curadoria.

        Usa o mesmo padrão model_dump/model_validate de
        `iniciar_contexto` (ddf.domain.model.analysis) — qualquer campo novo
        em ColunaExtraida/TabelaExtraida que também exista em
        ColunaCurada/TabelaCurada é copiado automaticamente; se não existir,
        model_validate levanta ValidationError, forçando decisão explícita.

        Args:
            tabela: tabela extraída, sem curadoria.

        Returns:
            TabelaCurada com a mesma estrutura, curadoria vazia (defaults).
        """
        colunas = [
            ColunaCurada.model_validate(coluna.model_dump())
            for coluna in tabela.colunas
        ]
        return TabelaCurada(
            **tabela.model_dump(exclude={"colunas", "amostra"}),
            colunas=colunas,
            amostra=tabela.amostra,
        )

    def _aplicar_curadoria(
        self, tabela_traduzida: TabelaCurada, override: _TabelaSobrescritaYAML
    ) -> TabelaCurada:
        """Aplica papel_de_negocio/regras_de_negocio do YAML sobre a tradução."""
        colunas: list[ColunaCurada] = []
        for coluna in tabela_traduzida.colunas:
            override_coluna = override.colunas.get(coluna.nome)
            if override_coluna is None:
                colunas.append(coluna)
                continue
            colunas.append(
                coluna.model_copy(
                    update={
                        "papel_de_negocio": override_coluna.papel_de_negocio or None,
                        "regras_de_negocio": override_coluna.regras_de_negocio,
                    }
                )
            )
        return tabela_traduzida.model_copy(
            update={
                "papel_de_negocio": override.papel_de_negocio or None,
                "regras_de_negocio": override.regras_de_negocio,
                "colunas": colunas,
            }
        )

    def _gerar_skeleton(
        self,
        entrada: TabelaExtraida,
        tabela_traduzida: TabelaCurada,
        caminho: Path,
        hash_atual: str,
    ) -> Resultado[TabelaCurada]:
        """Escreve o skeleton YAML na 1ª execução e emite Aviso de criação."""
        self._escrever_yaml(entrada, caminho, hash_atual, override=None)
        aviso = Aviso(
            mensagem=(
                f"Sobrescrita de '{entrada.nome_escopo}.{entrada.nome_tabela}' "
                f"criada em '{caminho}' — preencha a curadoria e reexecute."
            ),
            origem=_ORIGEM,
        )
        return Sucesso(tabela_traduzida, avisos=[aviso])

    def _atualizar_skeleton(
        self,
        entrada: TabelaExtraida,
        tabela_traduzida: TabelaCurada,
        override: _TabelaSobrescritaYAML,
        caminho: Path,
        hash_atual: str,
    ) -> Resultado[TabelaCurada]:
        """Atualiza o skeleton preservando curadoria remanescente + Aviso de diff."""
        nomes_novos = {coluna.nome for coluna in entrada.colunas}
        nomes_antigos = set(override.colunas.keys())
        adicionadas = sorted(nomes_novos - nomes_antigos)
        removidas = sorted(nomes_antigos - nomes_novos)

        clausulas: list[str] = []
        if adicionadas:
            clausulas.append(f"colunas adicionadas: {adicionadas}")
        if removidas:
            clausulas.append(f"colunas removidas: {removidas}")
        if clausulas:
            mensagem = (
                f"Estrutura de '{entrada.nome_escopo}.{entrada.nome_tabela}' mudou: "
                + "; ".join(clausulas)
            )
        else:
            mensagem = (
                f"Estrutura de '{entrada.nome_escopo}.{entrada.nome_tabela}' mudou "
                "(nomes de coluna preservados, mas algum campo estrutural foi "
                "alterado)."
            )

        self._escrever_yaml(entrada, caminho, hash_atual, override=override)
        tabela_curada = self._aplicar_curadoria(tabela_traduzida, override)
        aviso = Aviso(mensagem=mensagem, origem=_ORIGEM)
        return Sucesso(tabela_curada, avisos=[aviso])

    def _escrever_yaml(
        self,
        entrada: TabelaExtraida,
        caminho: Path,
        hash_atual: str,
        override: _TabelaSobrescritaYAML | None,
    ) -> None:
        """Serializa o skeleton (novo ou atualizado) em disco."""
        colunas_yaml: dict[str, dict[str, str | list[str]]] = {}
        for coluna in entrada.colunas:
            override_coluna = override.colunas.get(coluna.nome) if override else None
            if override_coluna is None:
                colunas_yaml[coluna.nome] = {
                    "papel_de_negocio": "",
                    "regras_de_negocio": [],
                }
            else:
                colunas_yaml[coluna.nome] = {
                    "papel_de_negocio": override_coluna.papel_de_negocio,
                    "regras_de_negocio": override_coluna.regras_de_negocio,
                }

        conteudo: dict[str, object] = {
            "hash": hash_atual,
            "papel_de_negocio": override.papel_de_negocio if override else "",
            "regras_de_negocio": override.regras_de_negocio if override else [],
            "colunas": colunas_yaml,
        }
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            yaml.safe_dump(conteudo, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

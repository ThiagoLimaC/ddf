# Instalação

## Requisito

Python 3.12 ou superior.

## Ambiente isolado (recomendado)

Antes de instalar, crie um ambiente virtual dedicado, para não misturar as dependências do
`ddf` com as de outros projetos Python na mesma máquina. Qualquer ferramenta de ambiente
virtual serve; duas opções comuns:

```bash
python -m venv .venv
source .venv/bin/activate
```

O próprio `ddf` é desenvolvido com [uv](https://docs.astral.sh/uv/), que também resolve
esse passo:

```bash
uv venv
source .venv/bin/activate
```

## Instalar

```bash
pip install ddf-framework
```

> O nome de publicação no PyPI é `ddf-framework`; o comando de linha de comando continua
> sendo `ddf`.

## Drivers de banco

Os drivers de conexão com Postgres (`psycopg2-binary`) e MariaDB (`pymysql`) já vêm como
dependência do pacote. Nenhum dos dois exige instalar um cliente de banco separado no
sistema operacional.

## Próximo passo

Com o `ddf` instalado, siga para o [Guia rápido](guia-rapido.md).

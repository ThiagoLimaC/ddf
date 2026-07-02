# Issue #4 — chore: setup do projeto

- [x] `uv init` + `pyproject.toml` (Python 3.12+, layout `src/`)
  - `uv` instalado via pipx em `~/.local/bin/uv` (fora do `$PATH` da sessão)
  - Comando usado: `uv init --package --name ddf --python 3.12 .`
- [x] Dependências de produção: `pydantic`, `psycopg2-binary`, `polars`,
      `jinja2`, `pyyaml`, `click`, `questionary`
  - `uv add pydantic psycopg2-binary polars jinja2 pyyaml click questionary`
- [x] Dependências de dev: `ruff`, `mypy`, `pytest`
  - `uv add --dev ruff mypy pytest`
- [x] Estrutura de pastas `src/ddf/domain/{model,ports,shared}`,
      `src/ddf/pipeline/`,
      `src/ddf/infrastructure/adapters/{extractors,analyzers,generators,orchestrator,overrides,cli}`,
      `tests/unit/...`, `tests/integration/...`
  - `__init__.py` vazio em cada pacote de `src/ddf/` (necessário p/ mypy/import)
  - `tests/` sem `__init__.py` (pytest não exige; `conftest.py` entra por
    camada só quando o primeiro teste daquela camada for escrito, Task 2+)
- [x] `[tool.ruff.lint]` em `pyproject.toml`
      (`select = ["E","F","W","I","N","D"]`, `pydocstyle convention = "google"`)
- [x] `[tool.mypy]` com `strict = true`
  - `files = ["src"]` em ambos os tools, escopando para o pacote
- [x] Workflow de CI em `.github/workflows/ci.yml`
      (`uv sync` + `ruff check` + `mypy --strict` + `pytest`)
  - `pytest` sem testes retorna exit code 5 ("no tests collected"); step do
    CI aceita esse código explicitamente até a Task 2 trazer testes reais
  - Gatilho só em `pull_request` (não em `push`) — evita rodar o CI em
    duplicidade; push direto na branch não dispara nada, só o PR
- [x] Verificação: `ruff check .`, `mypy --strict src`, `pytest`
  - Adicionadas docstrings de uma linha nos `__init__.py` (ruff `D104`/`D103`)
  - `ruff check .`: OK · `mypy --strict src`: OK (14 arquivos) ·
    `pytest`: 0 testes coletados (esperado nesta task)

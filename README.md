# alq-epub-converter (`alq`)

Conversor de arquivos PDF para EPUB baseado em terminal (CLI), construído com arquitetura híbrida em **Rust** (orquestração de CLI, validação e progresso no terminal) e **Python** (extração de PDF, reconstrução textual/estrutural e geração do pacote EPUB).

## Pré-requisitos

- **Rust** (`rustc` e `cargo` estáveis; `rustfmt` e `clippy` para verificação)
- **Python 3.12+**
- **uv** (gerenciador de ambientes e pacotes Python)

## Estrutura do Repositório

```text
.
├── Cargo.toml                 # Manifesto único Cargo (binário e lib `alq`)
├── rust/
│   └── src/                   # Camada CLI/orquestração em Rust
├── python/
│   ├── pyproject.toml         # Manifesto do pacote Python `alq`
│   └── src/alq/               # Pipeline de conversão PDF -> EPUB
│       ├── domain/            # Modelos intermediários de documento
│       ├── pdf/               # Leitura e extração via PyMuPDF
│       ├── processing/        # Limpeza, parágrafos, títulos e normalização
│       └── epub/              # Construção de capítulos, CSS, TOC e EPUB
├── tests/
│   ├── rust/                  # Testes unitários/integração Rust
│   ├── python/                # Suíte pytest do pacote `alq`
│   ├── integration/           # Testes ponta a ponta
│   └── fixtures/              # Arquivos de exemplo para testes
├── examples/                  # Exemplos de entrada/uso
└── output/                    # Diretório de saída local (ignorado no Git)
```

## Desenvolvimento e Verificação

### 1. Instalar dependências

```bash
cargo fetch
uv --directory python sync
```

### 2. Verificações Rust

```bash
cargo fmt --check
cargo check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

### 3. Verificações Python (via `uv`)

```bash
uv --directory python run ruff check . ../tests/python
uv --directory python run ruff format --check . ../tests/python
uv --directory python run mypy
uv --directory python run pytest
uv --directory python run python -m alq
```

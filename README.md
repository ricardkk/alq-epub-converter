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

## Uso da CLI (`alq`)

### Ajuda Geral e Subcomandos

```bash
alq --help
alq convert --help
alq inspect --help
```

### 1. Converter PDF para EPUB (`alq convert`)

```bash
alq convert <INPUT> [--output <OUTPUT>] [--language <LANG>] [--debug] [--overwrite]
```

| Argumento / Flag | Curta | Obrigatório | Descrição |
|---|---|---|---|
| `<INPUT>` | — | Sim | Caminho do arquivo PDF de entrada (`.pdf` válido com cabeçalho `%PDF-`). |
| `--output <OUTPUT>` | `-o` | Não | Caminho do arquivo `.epub` de saída. Padrão: mesmo diretório e nome-base da entrada com extensão `.epub`. |
| `--language <LANG>` | `-l` | Não | Código de idioma principal do documento (ex.: `pt-BR`, `en`). |
| `--debug` | — | Não | Ativa logs técnicos detalhados para depuração. |
| `--overwrite` | — | Não | Permite sobrescrever o arquivo de saída caso ele já exista. |

### 2. Inspecionar PDF (`alq inspect`)

```bash
alq inspect <INPUT> [--json]
```

| Argumento / Flag | Obrigatório | Descrição |
|---|---|---|
| `<INPUT>` | Sim | Caminho do arquivo PDF de entrada. |
| `--json` | Não | Exibe o resultado da inspeção formatado em JSON no `stdout`. |

### Variáveis de Ambiente

- `ALQ_PYTHON`: Caminho explícito para o executável Python a ser invocado pelo runner Rust (prioridade máxima).
- `PDF2EPUB_PYTHON`: Fallback de compatibilidade para definir o executável Python caso `ALQ_PYTHON` não esteja definido.
- Caso nenhuma variável seja informada, o `alq` procura automaticamente `python/.venv/bin/python` e, como último recurso, `python3` no `PATH`.

## Códigos de Saída (`Exit Codes`) e Códigos de Erro

### Códigos de Saída do Processo

| Exit Code | Constante | Significado |
|---|---|---|
| `0` | `EXIT_SUCCESS` | Operação concluída com sucesso (ou exibição de `--help` / `--version`). |
| `1` | `EXIT_RUNTIME_ERROR` | Erro de execução: falha ao iniciar o Python, erro no subprocesso, violação do protocolo JSON v1 ou falha durante a conversão. |
| `2` | `EXIT_VALIDATION_ERROR` | Erro de validação ou uso: argumentos ausentes/inválidos na CLI, entrada inexistente, arquivo inválido ou arquivo de saída já existente sem `--overwrite`. |

### Códigos de Erro Padronizados

| Código de Erro | Exit Code | Condição |
|---|---|---|
| `INPUT_NOT_FOUND` | `2` | O arquivo de entrada informado não existe. |
| `INVALID_INPUT` | `2` | A entrada é um diretório, não possui extensão `.pdf` / assinatura `%PDF-`, ou o caminho de saída é inválido (diretório ou idêntico à entrada). |
| `OUTPUT_EXISTS` | `2` | O arquivo `.epub` de saída já existe e `--overwrite` não foi informado. |
| `PYTHON_NOT_FOUND` | `1` | O interpretador Python não foi encontrado ou não pôde ser executado. |
| `RUNNER_FAILED` | `1` | O subprocesso Python encerrou com código de erro inesperado. |
| `PROTOCOL_ERROR` | `1` | A saída em `stdout` do worker Python não é um JSON v1 válido (`schema_version: 1`). |
| `CONVERSION_FAILED` | `1` | O worker Python reportou falha estruturada durante o processamento do documento. |
| `IO_ERROR` | `1` | Falha de leitura/escrita ou permissão no sistema de arquivos. |

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

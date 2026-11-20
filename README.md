# alq-epub-converter (`alq`)

Conversor de arquivos PDF para EPUB 3 baseado em terminal (CLI), construído com arquitetura híbrida em **Rust** (orquestração de CLI, validação de caminhos, logging e progresso no terminal) e **Python** (extração estruturada de PDF, ordenação de layout, limpeza de cabeçalhos/rodapés, reconstrução de parágrafos/listas/capítulos, extração de imagens, OCR opcional e geração/validação do pacote EPUB 3).

## Instalação Rápida (Linux)

Para instalar o comando `alq` globalmente no seu usuário (`~/.local/bin/alq` e `~/.local/share/alq/.venv`):

```bash
curl -fsSL https://raw.githubusercontent.com/ricardkk/alq-epub-converter/main/install.sh | bash
```

Para desinstalar:

```bash
curl -fsSL https://raw.githubusercontent.com/ricardkk/alq-epub-converter/main/install.sh | bash -s -- --uninstall
```

## Pré-requisitos

- **Rust** (`rustc` e `cargo` estáveis; `rustfmt` e `clippy` para verificação)
- **Python 3.12+**
- **uv** (gerenciador de ambientes e pacotes Python)
- **Tesseract OCR** *(opcional, exigido apenas quando `--ocr auto` encontrar páginas digitalizadas sem texto ou quando `--ocr always` for utilizado)*
- **EPUBCheck** *(opcional, executado automaticamente após a validação estrutural interna se disponível no `PATH`)*

## Estrutura do Repositório

```text
.
├── Cargo.toml
├── rust/
│   └── src/
│       ├── cli.rs
│       ├── commands.rs
│       ├── config.rs
│       ├── error.rs
│       ├── lib.rs
│       ├── main.rs
│       ├── progress.rs
│       ├── protocol.rs
│       └── runner.rs
├── python/
│   ├── pyproject.toml
│   └── src/alq/
│       ├── cli.py
│       ├── errors.py
│       ├── pipeline.py
│       ├── protocol.py
│       ├── domain/
│       │   ├── blocks.py
│       │   ├── document.py
│       │   └── metadata.py
│       ├── pdf/
│       │   ├── image_extractor.py
│       │   ├── layout.py
│       │   ├── ocr.py
│       │   ├── reader.py
│       │   └── text_extractor.py
│       ├── processing/
│       │   ├── cleanup.py
│       │   ├── headings.py
│       │   ├── normalizer.py
│       │   └── paragraphs.py
│       └── epub/
│           ├── builder.py
│           ├── chapters.py
│           ├── navigation.py
│           ├── stylesheet.py
│           └── validator.py
└── tests/
    ├── rust/
    │   └── cli_tests.rs
    └── python/
        ├── test_debug_mode.py
        ├── test_epub_builder.py
        ├── test_epub_validator.py
        ├── test_headings.py
        ├── test_image_extractor.py
        ├── test_ocr.py
        ├── test_paragraphs.py
        ├── test_pipeline.py
        ├── test_protocol.py
        ├── test_reader.py
        ├── test_smoke.py
        └── test_text_extractor.py
```

## Funcionalidades da Pipeline

1. **Inspeção e Abertura Segura (`alq.pdf.reader`)**:
   - Validação de assinatura PDF, criptografia/senha (`PDF_PASSWORD_REQUIRED`), integridade estrutural (`PDF_OPEN_FAILED`), metadados reais (sem inventar valores ausentes), contagem de páginas com/sem texto, imagens e detecção de necessidade de OCR.
2. **Extração Estruturada e Ordenação de Layout (`alq.pdf.text_extractor`, `alq.pdf.layout`)**:
   - Extração de spans, linhas e blocos com coordenadas (`BoundingBox`), tamanho e nome de fonte, flags tipográficas (`is_bold`, `is_italic`) e detecção/ordenação de leitura em 1 ou 2 colunas (`column_index`).
3. **OCR Opcional com Tesseract (`alq.pdf.ocr`)**:
   - Modos `--ocr never` (padrão), `--ocr auto` (aplica OCR somente em páginas sem camada de texto nativo) e `--ocr always` (aplica OCR em todas as páginas), registrando avisos nas páginas reconhecidas.
4. **Limpeza e Reconstrução Estrutural (`alq.processing`)**:
   - Normalização Unicode NFC, remoção de caracteres invisíveis de controle e colapso de espaços horizontais;
   - Filtragem de números de página isolados e cabeçalhos/rodapés recorrentes nas margens superior e inferior;
   - Desifenização cautelosa no fim de linha (`-`, `\u2010`, `\u00ad`);
   - Reconstrução de parágrafos multilinha (incluindo junção através de mudança de página), separação por espaçamento vertical e recuo de primeira linha, e agrupamento de listas ordenadas e não-ordenadas;
   - Detecção heurística de títulos e capítulos (`h1`, `h2`, `h3`) baseada na mediana tipográfica do corpo e padrões estruturais/numéricos.
5. **Extração e Normalização de Imagens (`alq.pdf.image_extractor`)**:
   - Extração de imagens incorporadas via PyMuPDF e Pillow, filtrando elementos decorativos minúsculos, convertendo formatos não suportados diretamente pelo EPUB 3 (`BMP`, `TIFF`, `CMYK`, etc.) para `PNG` e intercalando `ImageBlock` na posição correta de leitura.
6. **Geração e Validação de EPUB 3 (`alq.epub`)**:
   - Construção de pacote EPUB 3 com `EbookLib`, escape rigoroso de XHTML (`html.escape`), folha de estilos responsiva (`styles/main.css`), sumário (`nav.xhtml` e `toc.ncx`) e inclusão exclusiva de assets referenciados;
   - Validação estrutural interna obrigatória (ZIP, `mimetype`, `META-INF/container.xml`, manifesto `.opf`, sintaxe XML/XHTML de todos os capítulos e verificação de existência de todas as imagens/stylesheets referenciados) + integração opcional com `epubcheck`.
7. **Diagnóstico e Modo `--debug`**:
   - Quando `--debug` (ou `ALQ_DEBUG=1`) está ativo em `alq convert`, grava artefatos completos em `.debug/<stem>-<timestamp>-<id>/` (`inspection.json`, `extracted.json`, `normalized.json`, `document.json`, `warnings.json` e `logs.txt`) sem deixar resíduos em execuções normais.

## Uso da CLI (`alq`)

### Ajuda Geral e Subcomandos

```bash
alq --help
alq convert --help
alq inspect --help
```

### 1. Converter PDF para EPUB (`alq convert`)

```bash
alq convert <INPUT> [--output <OUTPUT>] [--language <LANG>] [--ocr <MODE>] [--debug] [--overwrite]
```

| Argumento / Flag | Curta | Obrigatório | Descrição |
|---|---|---|---|
| `<INPUT>` | — | Sim | Caminho do arquivo PDF de entrada (`.pdf` válido com cabeçalho `%PDF-`). |
| `--output <OUTPUT>` | `-o` | Não | Caminho do arquivo `.epub` de saída. Padrão: mesmo diretório e nome-base da entrada com extensão `.epub`. |
| `--language <LANG>` | `-l` | Não | Código de idioma principal do documento (ex.: `pt-BR`, `en`). |
| `--ocr <MODE>` | — | Não | Modo de OCR para páginas sem texto extraível: `never` (padrão), `auto` ou `always`. |
| `--debug` | — | Não | Ativa logs técnicos no `stderr` e grava artefatos intermediários em `.debug/`. |
| `--overwrite` | — | Não | Permite sobrescrever o arquivo de saída caso ele já exista. |

Exemplo de saída textual (`alq convert livro.pdf`):

```text
Conversão concluída.
Arquivo: livro.epub
Páginas: 120
Capítulos: 12
Parágrafos: 845
Imagens: 3
```

### 2. Inspecionar PDF (`alq inspect`)

```bash
alq inspect <INPUT> [--json]
```

| Argumento / Flag | Obrigatório | Descrição |
|---|---|---|
| `<INPUT>` | Sim | Caminho do arquivo PDF de entrada. |
| `--json` | Não | Exibe o resultado estruturado da inspeção (Contrato JSON v1) no `stdout`. |

Exemplo de saída textual (`alq inspect livro.pdf`):

```text
Arquivo: livro.pdf
Páginas: 120 (com texto: 120, sem texto: 0)
Metadados:
  Título: Dom Casmurro
  Autor: Machado de Assis
  Idioma: pt-BR
  Identificador: não informado
Imagens: 3
Dimensões da página: 595.00 x 842.00 pt
Necessidade provável de OCR: Não
```

### Variáveis de Ambiente

- `ALQ_PYTHON` / `PDF2EPUB_PYTHON`: Caminho explícito para o executável Python a ser invocado pelo runner Rust. Caso não definido, o `alq` utiliza `python/.venv/bin/python` e, como fallback, `python3` no `PATH`.
- `ALQ_DEBUG` / `PDF2EPUB_DEBUG`: Quando definido como `1` ou `true`, habilita o modo de depuração.
- `ALQ_DEBUG_DIR`: Sobrescreve o diretório base onde as pastas de execução do modo `--debug` são criadas.
- `ALQ_TESSERACT_BIN`: Caminho explícito para o executável `tesseract` utilizado pelo módulo de OCR.

## Códigos de Saída (`Exit Codes`) e Códigos de Erro

### Códigos de Saída do Processo

| Exit Code | Constante | Significado |
|---|---|---|
| `0` | `EXIT_SUCCESS` | Operação concluída com sucesso (ou exibição de `--help` / `--version`). |
| `1` | `EXIT_RUNTIME_ERROR` | Erro de execução: falha ao iniciar o Python, erro no subprocesso, violação do protocolo JSON v1 ou falha durante a extração/conversão/validação. |
| `2` | `EXIT_VALIDATION_ERROR` | Erro de validação ou uso: argumentos ausentes/inválidos na CLI, entrada inexistente, arquivo inválido ou arquivo de saída já existente sem `--overwrite`. |

### Códigos de Erro Padronizados

| Código de Erro | Exit Code | Condição |
|---|---|---|
| `INPUT_NOT_FOUND` | `2` | O arquivo de entrada informado não existe. |
| `INVALID_INPUT` | `2` | A entrada é um diretório, não possui extensão `.pdf` / assinatura `%PDF-`, ou o caminho de saída é inválido. |
| `OUTPUT_EXISTS` | `2` | O arquivo `.epub` de saída já existe e `--overwrite` não foi informado. |
| `PYTHON_NOT_FOUND` | `1` | O interpretador Python não foi encontrado ou não pôde ser iniciado. |
| `PYTHON_EXECUTION_FAILED` | `1` | O subprocesso Python encerrou inesperadamente sem emitir JSON válido. |
| `PROTOCOL_ERROR` | `1` | A saída em `stdout` do worker Python violou o Contrato JSON v1 (`schema_version: 1`). |
| `PDF_OPEN_FAILED` | `1` | O arquivo PDF está corrompido, truncado, vazio ou não pôde ser aberto pelo PyMuPDF. |
| `PDF_PASSWORD_REQUIRED` | `1` | O arquivo PDF está protegido por senha (`needs_pass`). |
| `NO_EXTRACTABLE_TEXT` | `1` | Nenhum texto extraível foi encontrado no documento PDF. |
| `TEXT_EXTRACTION_FAILED` | `1` | Falha ao extrair blocos de texto ou executar OCR nas páginas do PDF. |
| `EPUB_BUILD_FAILED` | `1` | Falha durante a construção ou gravação do pacote EPUB. |
| `EPUB_VALIDATION_FAILED` | `1` | O pacote EPUB gerado falhou na validação estrutural obrigatória. |
| `CONVERSION_FAILED` | `1` | Erro geral durante o pipeline de conversão. |
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
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

### 3. Verificações Python (via `uv`)

```bash
uv --directory python run ruff check . ../tests/python
uv --directory python run ruff format --check . ../tests/python
uv --directory python run mypy
uv --directory python run pytest
```

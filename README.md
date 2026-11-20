# alq-epub-converter (`alq`)

O `alq` é um conversor de PDF para EPUB 3 feito para rodar no terminal. Ele foi criado para transformar livros e artigos em PDF em arquivos mais confortáveis de ler em e-readers e celulares.

Durante a conversão, o programa lê o texto em uma ou duas colunas, junta parágrafos quebrados entre páginas e colunas, limpa cabeçalhos e números de página repetidos, organiza capítulos no sumário e mantém as imagens incorporadas na ordem de leitura. Para PDFs digitalizados sem texto selecionável, também oferece OCR opcional com Tesseract.

## Instalação

No Linux, o script de instalação compila o binário e configura o ambiente Python automaticamente em `~/.local/bin/alq` e `~/.local/share/alq/.venv`:

```bash
curl -fsSL https://raw.githubusercontent.com/ricardkk/alq-epub-converter/main/install.sh | bash
```

Você precisa ter `cargo` (Rust) e `uv` ou Python 3.12+ instalados na máquina. Se quiser converter PDFs escaneados, instale também o `tesseract`. O `epubcheck` é opcional: se estiver no `PATH`, o `alq` o executa ao final da conversão para validar o EPUB.

Para atualizar depois, rode o mesmo comando de instalação. Para remover o programa e o ambiente criado:

```bash
curl -fsSL https://raw.githubusercontent.com/ricardkk/alq-epub-converter/main/install.sh | bash -s -- --uninstall
```

## Como usar

### 1. Inspecionar um PDF antes de converter

Se você não sabe se o PDF tem texto selecionável ou se vai precisar de OCR, rode `alq inspect`:

```bash
alq inspect livro.pdf
```

A saída mostra o total de páginas com e sem texto, metadados do arquivo, quantidade de imagens e se o OCR provavelmente será necessário:

```text
Arquivo: livro.pdf
Páginas: 226 (com texto: 226, sem texto: 0)
Metadados:
  Título: não informado
  Autor: não informado
  Idioma: und
  Identificador: não informado
Imagens: 0
Dimensões da página: 283.46 x 425.20 pt
Necessidade provável de OCR: Não
```

Para integrar com scripts, passe `--json` no final do comando.

### 2. Converter para EPUB

Para o caso comum, basta passar o caminho do PDF:

```bash
alq convert livro.pdf
```

O arquivo `livro.epub` é criado na mesma pasta do PDF original. Ao concluir, o terminal exibe um resumo:

```text
Conversão concluída.
Arquivo: livro.epub
Páginas: 226
Capítulos: 37
Parágrafos: 675
Imagens: 0
```

### 3. Exemplos do dia a dia

Salvar o EPUB em outra pasta ou com outro nome:

```bash
alq convert livro.pdf -o ~/Livros/meu-livro.epub
```

Sobrescrever um EPUB que já existe no destino (por segurança, o `alq` não apaga arquivos existentes sem essa flag):

```bash
alq convert livro.pdf --overwrite
```

Definir o idioma do livro quando o PDF não informa esse metadado:

```bash
alq convert livro.pdf -l pt-BR
```

Converter um PDF digitalizado usando OCR apenas nas páginas sem texto:

```bash
alq convert digitalizado.pdf --ocr auto -l pt-BR
```

Se quiser forçar OCR em todas as páginas (útil quando a camada de texto embutida no PDF está muito corrompida), troque para `--ocr always`.

Investigar algum problema na conversão gravando os arquivos intermediários em `.debug/`:

```bash
alq convert livro.pdf --debug --overwrite
```

## Referência de opções

### `alq convert`

| Opção | Descrição |
|---|---|
| `<INPUT>` | Caminho do arquivo `.pdf` de entrada (obrigatório). |
| `-o`, `--output <OUTPUT>` | Caminho do `.epub` de saída. Padrão: mesma pasta e nome do PDF. |
| `-l`, `--language <LANG>` | Idioma principal do livro (por exemplo, `pt-BR` ou `en`). |
| `--ocr <MODE>` | Modo de OCR: `never` (padrão), `auto` ou `always`. |
| `--overwrite` | Permite substituir o arquivo `.epub` caso ele já exista. |
| `--debug` | Exibe logs detalhados e grava arquivos de diagnóstico em `.debug/`. |

### `alq inspect`

| Opção | Descrição |
|---|---|
| `<INPUT>` | Caminho do arquivo `.pdf` de entrada (obrigatório). |
| `--json` | Imprime o resultado da inspeção em JSON no `stdout`. |

Para ver a ajuda completa no terminal, use `alq --help`, `alq convert --help` ou `alq inspect --help`.

## Problemas comuns

O comando `alq` não foi encontrado após instalar: verifique se `~/.local/bin` está no seu `PATH`. No Bash, adicione `export PATH="$HOME/.local/bin:$PATH"` ao `~/.bashrc` e rode `source ~/.bashrc`.

O PDF não tem texto extraível: rode `alq inspect arquivo.pdf` para confirmar se há páginas sem texto e converta com `--ocr auto` (com o `tesseract` instalado).

O arquivo de saída já existe: passe `--overwrite` ou escolha outro caminho com `-o`.

O PDF pede senha: o `alq` não remove proteção de senha. Desbloqueie o arquivo antes de converter.

Erros de ortografia no EPUB: quando o PDF já possui texto embutido, o `alq` lê esse texto diretamente. Se o PDF original veio de um OCR antigo com erros, esses erros aparecem no resultado; nesses casos, tente converter com `--ocr always`.

## Variáveis de ambiente opcionais

Se precisar apontar caminhos personalizados, o `alq` aceita:

- `ALQ_PYTHON`: caminho explícito do executável Python a ser usado.
- `ALQ_TESSERACT_BIN`: caminho explícito do binário `tesseract`.
- `ALQ_DEBUG`: defina como `1` para ativar logs detalhados sem passar `--debug`.
- `ALQ_DEBUG_DIR`: pasta base onde os diretórios de diagnóstico do modo `--debug` são salvos.

## Desenvolvimento local

O projeto combina uma CLI em Rust (`rust/`) com o processamento de PDF e geração de EPUB em Python (`python/`). Para rodar localmente a partir do repositório:

```bash
cargo fetch
uv --directory python sync
```

Verificações de código e testes:

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test

uv --directory python run ruff check . ../tests/python
uv --directory python run ruff format --check . ../tests/python
uv --directory python run mypy
uv --directory python run pytest
```

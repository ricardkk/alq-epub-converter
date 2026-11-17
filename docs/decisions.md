# Decisões Arquiteturais e Planejamento Técnico — `alq-epub-converter`

**Status:** Fase 0 (Inspeção e planejamento técnico)  
**Data:** 2026-11-17

---

## 1. Inspeção do Ambiente e Repositório

Estado inicial do repositório verificado:
- Apenas `README.md` presente (`# alq-epub-converter`).

Versões confirmadas das ferramentas no ambiente (`PATH` incluindo `/home/ricardo/.cargo/bin`):
- **Rustc:** `rustc 1.100.0 (0ef1bc386 2026-11-09)`
- **Cargo:** `cargo 1.100.0 (3acc79c0c 2026-11-05)`
- **Clippy:** `clippy 0.1.100 (0ef1bc3860 2026-11-09)`
- **Rustfmt:** `rustfmt 1.11.0-stable (0ef1bc3860 2026-11-09)`
- **uv:** `uv 0.13.9 (x86_64-unknown-linux-gnu)`
- **Python:** `Python 3.12.3` (`/usr/bin/python3`)

---

## 2. Decisão de Nomenclatura

- **Repositório:** `alq-epub-converter`
- **Binário CLI (Rust):** `alq`
- **Pacote / Módulo Python:** `alq` (executado via `python -m alq`)

Essa unificação evita divergências entre o comando invocado pelo usuário final, os logs do sistema e o entrypoint do worker Python.

---

## 3. Arquitetura: Monólito Modular Híbrido (Rust + Python)

O projeto adota uma arquitetura de **monólito modular** em um único repositório, separando claramente responsabilidades entre duas camadas:

1. **Camada Rust (`alq` CLI — Orquestrador e UX de Terminal):**
   - Parsing de argumentos e flags de linha de comando.
   - Validação de caminhos de entrada/saída, permissões e pré-condições antes de iniciar a conversão.
   - Exibição de barra de progresso e feedback de terminal ao usuário.
   - Invocação segura do processo Python via `std::process::Command` com argumentos explícitos (sem uso de shell / `sh -c`, prevenindo injeção de comandos).
   - Consumo em streaming do `stderr` para atualização de progresso em tempo real e parsing estrito do payload final em `stdout`.

2. **Camada Python (`alq` — Pipeline de Conversão PDF → EPUB):**
   - Leitura e inspeção do PDF (metadados, páginas, blocos de texto, estilos/fontes, imagens).
   - Normalização textual e reconstrução estrutural (parágrafos, hifenização, detecção de capítulos/TOC, limpeza de ruído).
   - Processamento de imagens/capa e empacotamento final em EPUB.

---

## 4. Integração via Subprocesso e Contrato JSON v1

A comunicação entre o binário Rust e o módulo Python ocorre exclusivamente via subprocesso com separação estrita dos fluxos padrão:

- **`stdout` (Contrato JSON v1):**
  - Reservado **exclusivamente** para um único objeto JSON emitido ao final da execução.
  - Deve conter obrigatoriamente `"schema_version": 1`, além do status da operação, métricas/metadados do documento convertido, caminho de saída ou erro estruturado.
  - Nenhum log, aviso ou saída de depuração pode ser impresso em `stdout`, garantindo parsing determinístico pelo Rust.

- **`stderr` (Logs e Progresso em Tempo Real):**
  - Reservado para logs técnicos diagnósticos e eventos estruturados de progresso em streaming.
  - Eventos prefixados (ex.: `STAGE:<etapa>:<progresso>:<mensagem>`) permitem que o Rust atualize a barra de progresso (`indicatif`) em tempo real sem poluir o `stdout`.

---

## 5. Estrutura do Manifesto Cargo

Optou-se por um **manifesto `Cargo.toml` único na raiz do repositório**, sem Cargo workspace duplicado:
- `[[bin]]` com `name = "alq"` apontando para `rust/src/main.rs`.
- `[lib]` com `name = "alq"` (ou `alq_epub_converter` / `alq_core`, conforme convenção da crate) apontando para `rust/src/lib.rs`.

Essa organização mantém a raiz limpa, simplifica o build (`cargo build` / `cargo test` direto na raiz) e isola o código-fonte Rust em `rust/src/` enquanto o código Python reside em `python/` (ou `src/alq/` conforme definição do `pyproject.toml`).

---

## 6. Stack de Bibliotecas e Compatibilidade

### 6.1 Rust
| Crate | Finalidade |
|---|---|
| `clap` (feature `derive`) | Definição declarativa da interface CLI (`alq`) |
| `serde` + `serde_json` | Serialização e desserialização do Contrato JSON v1 |
| `thiserror` | Definição de tipos de erro explícitos na camada de biblioteca |
| `anyhow` | Tratamento e contexto de erros na camada de aplicação/CLI |
| `tracing` + `tracing-subscriber` | Instrumentação e logging técnico estruturado |
| `indicatif` | Barra de progresso e indicadores de etapa no terminal |
| `tempfile` (`dev-dependencies`) | Criação de arquivos e diretórios temporários em testes |

### 6.2 Python (`>= 3.12`)
| Pacote | Finalidade |
|---|---|
| `pymupdf` | Extração de texto, metadados, geometria de blocos, fontes e imagens de PDFs |
| `pillow` | Processamento, redimensionamento e conversão de imagens e capas |
| `ebooklib` | Construção da estrutura interna, metadados, TOC e empacotamento EPUB |
| `pytest` (dev) | Suíte de testes unitários e de integração |
| `ruff` (dev) | Linter e formatador de código Python |
| `mypy` (dev) | Verificação estática de tipagem |

---

## 7. Licenças e Requisitos Nativos

- **PyMuPDF (MuPDF) e EbookLib:** distribuídos sob licença **AGPLv3**, compatível com uso próprio e projetos open-source compatíveis com AGPLv3. (Nota: eventual distribuição comercial fechada ou serviço em rede exigiria atenção às obrigações da AGPLv3 ou aquisição de licença comercial da Artifex para o MuPDF).
- **Pillow:** distribuído sob licença **MIT-CMU / HPND** (permissiva).
- **Dependências nativas:** os wheels pré-compilados do `pymupdf` para Linux `x86_64` já embarcam as bibliotecas nativas do MuPDF, não exigindo compilação C local nem pacotes de sistema extras para instalação padrão via `uv`.

---

## 8. Limitações Conhecidas do MVP

1. **Sem OCR inicial:** PDFs compostos apenas por imagens digitalizadas (sem camada de texto) não terão texto extraído no MVP.
2. **Layouts complexos:** tabelas complexas e documentos com múltiplas colunas podem sofrer perda ou embaralhamento de ordem de leitura.
3. **Cabeçalhos e rodapés:** a filtragem heurística prioritária de cabeçalhos e rodapés repetitivos está planejada para a **Fase 6**.
4. **Validação de EPUB:** o MVP realizará validação estrutural interna leve no próprio pipeline; a validação completa via **EPUBCheck** (dependência externa Java) será tratada como opcional.

---

## 9. Plano de Comandos de Build, Lint e Teste

Sempre garantir `/home/ricardo/.cargo/bin` no `PATH` quando necessário (`export PATH="/home/ricardo/.cargo/bin:$PATH"`).

### Rust
- **Formatação:** `cargo fmt --check` (aplicar com `cargo fmt`)
- **Lint:** `cargo clippy --all-targets -- -D warnings`
- **Testes:** `cargo test`
- **Build:** `cargo build` / `cargo build --release`

### Python (via `uv`)
- **Lint e formatação:** `uv run ruff check .` e `uv run ruff format --check .`
- **Checagem de tipos:** `uv run mypy` (apontando para o pacote `alq`)
- **Testes:** `uv run pytest`

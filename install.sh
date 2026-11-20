#!/usr/bin/env bash
set -euo pipefail

REPO="${ALQ_REPO:-ricardkk/alq-epub-converter}"
REF="${ALQ_REF:-main}"
BIN_DIR="${ALQ_BIN_DIR:-$HOME/.local/bin}"
DATA_DIR="${ALQ_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/alq}"
VENV_DIR="$DATA_DIR/.venv"
SOURCE_DIR="${ALQ_SOURCE_DIR:-}"

log() {
  printf '[alq] %s\n' "$*"
}

die() {
  printf '[alq] Erro: %s\n' "$*" >&2
  exit 1
}

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$BIN_DIR/alq"
  rm -rf "$DATA_DIR"
  log "alq removido de $BIN_DIR/alq e $DATA_DIR"
  exit 0
fi

if [[ -f "$HOME/.cargo/env" ]]; then
  source "$HOME/.cargo/env"
fi

if ! command -v cargo >/dev/null 2>&1; then
  die "cargo não encontrado. Instale o Rust com: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
fi

TMP_DIR=""
cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

if [[ -n "$SOURCE_DIR" ]]; then
  [[ -d "$SOURCE_DIR" ]] || die "ALQ_SOURCE_DIR não encontrado: $SOURCE_DIR"
  WORK_SRC="$SOURCE_DIR"
else
  command -v curl >/dev/null 2>&1 || die "curl é obrigatório para baixar o código-fonte."
  command -v tar >/dev/null 2>&1 || die "tar é obrigatório para extrair o pacote."

  TMP_DIR="$(mktemp -d)"
  ARCHIVE_URL="https://github.com/${REPO}/archive/${REF}.tar.gz"
  log "Baixando código-fonte de ${ARCHIVE_URL}..."
  curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz"
  tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR"
  WORK_SRC="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "$WORK_SRC" && -f "$WORK_SRC/Cargo.toml" ]] || die "Falha ao localizar Cargo.toml no pacote baixado."
fi

mkdir -p "$BIN_DIR" "$DATA_DIR"

UV_BIN=""
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
fi

if [[ -n "$UV_BIN" ]]; then
  log "Configurando ambiente Python com uv em $VENV_DIR..."
  "$UV_BIN" venv --clear --python ">=3.12" "$VENV_DIR"
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" "$WORK_SRC/python"
else
  command -v python3 >/dev/null 2>&1 || die "python3 ou uv é obrigatório para instalar o worker Python."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || \
    die "Python 3.12+ é obrigatório (ou instale o uv: curl -LsSf https://astral.sh/uv/install.sh | sh)."
  log "Configurando ambiente Python com python3 em $VENV_DIR..."
  python3 -m venv --clear "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install "$WORK_SRC/python"
fi

log "Compilando binário Rust em modo release..."
cargo build --release --manifest-path "$WORK_SRC/Cargo.toml"

BIN_SRC="$WORK_SRC/target/release/alq"
[[ -x "$BIN_SRC" ]] || die "Binário compilado não encontrado em $BIN_SRC."

install -m 755 "$BIN_SRC" "$BIN_DIR/alq"

VERSION_OUT="$("$BIN_DIR/alq" --version)"
log "Instalação concluída: $VERSION_OUT"
log "Binário: $BIN_DIR/alq"
log "Ambiente Python: $VENV_DIR"

case ":$PATH:" in
  *":$BIN_DIR:"*)
    log "O comando 'alq' já está disponível no seu PATH."
    ;;
  *)
    log "Adicione $BIN_DIR ao seu PATH para usar 'alq' em qualquer pasta:"
    printf '  echo '\''export PATH="%s:$PATH"'\'' >> ~/.bashrc && source ~/.bashrc\n' "$BIN_DIR"
    ;;
esac

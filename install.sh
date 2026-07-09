#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

RED='\033[91m'
GREEN='\033[92m'
CYAN='\033[96m'
RESET='\033[0m'

ok() {
    printf '%b\n' "${GREEN}[OK]${RESET} $1"
}

info() {
    printf '%b\n' "${CYAN}[INFO]${RESET} $1"
}

err() {
    printf '%b\n' "${RED}[ERR]${RESET} $1" >&2
}

if [ "$(id -u)" -ne 0 ]; then
    err "Installation requires root privileges. Try: sudo sh install.sh"
    exit 1
fi

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="/opt/lixet"
MAIN_SCRIPT="$INSTALL_DIR/main.py"
BIN_PATH="/usr/local/bin/lixet"

if [ ! -f "$BASE_DIR/main.py" ]; then
    err "Could not find entry point: $BASE_DIR/main.py"
    exit 1
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

tar \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='env' \
    --exclude='developer' \
    --exclude='docker' \
    --exclude='tests' \
    --exclude='*.bak' \
    --exclude='*.lixet.*.bak' \
    -C "$BASE_DIR" -cf - . | tar -C "$INSTALL_DIR" -xf -

chmod +x "$MAIN_SCRIPT"
ln -sf "$MAIN_SCRIPT" "$BIN_PATH"
ok "Installed lixet -> $MAIN_SCRIPT"
info "Command available as: lixet"

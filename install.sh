#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Installation requires root privileges. Try: sudo sh install.sh" >&2
    exit 1
fi

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="/opt/lixet"
MAIN_SCRIPT="$INSTALL_DIR/main.py"
BIN_PATH="/usr/local/bin/lixet"

if [ ! -f "$BASE_DIR/main.py" ]; then
    echo "Could not find entry point: $BASE_DIR/main.py" >&2
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
echo "Installed lixet -> $MAIN_SCRIPT"
echo "Command available as: lixet"

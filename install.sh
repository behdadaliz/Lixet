#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Installation requires root privileges. Try: sudo sh install.sh" >&2
    exit 1
fi

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MAIN_SCRIPT="$BASE_DIR/main.py"
BIN_PATH="/usr/local/bin/lixet"

if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "Could not find entry point: $MAIN_SCRIPT" >&2
    exit 1
fi

chmod +x "$MAIN_SCRIPT"
ln -sf "$MAIN_SCRIPT" "$BIN_PATH"
echo "Installed lixet -> $MAIN_SCRIPT"

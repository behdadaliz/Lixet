#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

BIN_PATH="/usr/local/bin/lixet"

if [ "$(id -u)" -ne 0 ]; then
    echo "Uninstall requires root privileges. Try: sudo sh uninstall.sh" >&2
    exit 1
fi

if [ -e "$BIN_PATH" ] || [ -L "$BIN_PATH" ]; then
    rm -f "$BIN_PATH"
    echo "Removed $BIN_PATH"
else
    echo "$BIN_PATH is not installed"
fi

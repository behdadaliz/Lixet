#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

RED='\033[91m'
GREEN='\033[92m'
CYAN='\033[96m'
RESET='\033[0m'

color() {
    if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
        printf '%b' "$1$2$RESET"
    else
        printf '%s' "$2"
    fi
}

ok() {
    printf '%s %s\n' "$(color "$GREEN" "[OK]")" "$1"
}

info() {
    printf '%s %s\n' "$(color "$CYAN" "[INFO]")" "$1"
}

err() {
    printf '%s %s\n' "$(color "$RED" "[ERR]")" "$1" >&2
}

BIN_PATH="/usr/local/bin/lixet"
INSTALL_DIR="/opt/lixet"

if [ "$(id -u)" -ne 0 ]; then
    err "Uninstall requires root privileges. Try: sudo sh uninstall.sh"
    exit 1
fi

if [ -e "$BIN_PATH" ] || [ -L "$BIN_PATH" ]; then
    rm -f "$BIN_PATH"
    ok "Removed $BIN_PATH"
else
    info "$BIN_PATH is not installed"
fi

if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
fi

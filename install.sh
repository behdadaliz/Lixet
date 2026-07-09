#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -u

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

fail() {
    if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
    if [ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        mv "$BACKUP_DIR" "$INSTALL_DIR" 2>/dev/null || true
        ln -sfn "$MAIN_SCRIPT" "$BIN_PATH" 2>/dev/null || true
    elif [ -d "${INSTALL_DIR:-}" ] && [ "${INSTALL_STARTED:-0}" = "1" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    err "$1"
    exit 1
}

validate_tree() {
    ROOT="$1"
    for path in VERSION main.py install.py cli core services validators repair backup utils; do
        if [ ! -e "$ROOT/$path" ]; then
            fail "Missing required project file: $path"
        fi
    done
    if ! grep -Eq '^[0-9]+(\.[0-9]+){1,3}(-(alpha|beta|rc))?$' "$ROOT/VERSION"; then
        fail "VERSION must contain a clean semantic version, such as 0.2.0-beta"
    fi
}

if [ "$(id -u)" -ne 0 ]; then
    err "Installation requires root privileges. Try: sudo sh install.sh"
    exit 1
fi

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="/opt/lixet"
INSTALL_PARENT="/opt"
MAIN_SCRIPT="$INSTALL_DIR/main.py"
BIN_PATH="/usr/local/bin/lixet"
TMP_DIR=""
BACKUP_DIR=""
INSTALL_STARTED=0

validate_tree "$BASE_DIR"

mkdir -p "$INSTALL_PARENT" || fail "Could not create /opt."
TMP_DIR=$(mktemp -d "$INSTALL_PARENT/.lixet-install.XXXXXX") || fail "Could not create temporary install directory."

if ! tar \
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
    -C "$BASE_DIR" -cf - . | tar -C "$TMP_DIR" -xf -; then
    fail "Could not copy project files."
fi

validate_tree "$TMP_DIR"
chmod +x "$TMP_DIR/main.py" || fail "Could not mark main.py as executable."

if [ -d "$INSTALL_DIR" ]; then
    BACKUP_DIR="$INSTALL_PARENT/.lixet-install-backup-$(date +%Y%m%d_%H%M%S)"
    mv "$INSTALL_DIR" "$BACKUP_DIR" || fail "Could not prepare previous installation backup."
fi

INSTALL_STARTED=1
mv "$TMP_DIR" "$INSTALL_DIR" || fail "Could not move Lixet into /opt/lixet."
TMP_DIR=""
mkdir -p "$(dirname "$BIN_PATH")" || fail "Could not prepare command directory."
ln -sfn "$MAIN_SCRIPT" "$BIN_PATH" || fail "Could not create lixet command symlink."

if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf "$BACKUP_DIR"
fi

ok "Installed lixet -> $MAIN_SCRIPT"
info "Command available as: lixet"

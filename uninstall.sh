#!/usr/bin/env sh
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' '[ERR] Python 3.10 or newer is required.' >&2
    exit 4
fi

exec python3 "$BASE_DIR/install.py" uninstall "$@"

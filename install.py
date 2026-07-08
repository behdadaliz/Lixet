#!/usr/bin/env python3
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Install or uninstall the global lixet command."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

BIN_PATH = Path("/usr/local/bin/lixet")


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Installation requires root privileges. Try: sudo sh install.sh")


def install() -> None:
    require_root()
    base_dir = Path(__file__).resolve().parent
    main_script = base_dir / "main.py"
    if not main_script.exists():
        raise SystemExit(f"Could not find entry point: {main_script}")

    mode = stat.S_IMODE(main_script.stat().st_mode)
    main_script.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if BIN_PATH.exists() or BIN_PATH.is_symlink():
        BIN_PATH.unlink()
    BIN_PATH.symlink_to(main_script)
    print(f"Installed lixet -> {main_script}")


def uninstall() -> None:
    require_root()
    if BIN_PATH.exists() or BIN_PATH.is_symlink():
        BIN_PATH.unlink()
        print(f"Removed {BIN_PATH}")
    else:
        print(f"{BIN_PATH} is not installed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or uninstall Lixet")
    parser.add_argument("action", nargs="?", choices=("install", "uninstall"), default="install")
    args = parser.parse_args(argv)
    if args.action == "install":
        install()
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

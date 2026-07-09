#!/usr/bin/env python3
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Install or uninstall the global lixet command."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path

BIN_PATH = Path("/usr/local/bin/lixet")
INSTALL_DIR = Path("/opt/lixet")
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "developer", "docker", "tests"}
SKIP_NAMES = {".env"}
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"
RESET = "\033[0m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


def ok(message: str) -> None:
    print(f"{color('[OK]', GREEN)} {message}")


def info(message: str) -> None:
    print(f"{color('[INFO]', CYAN)} {message}")


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit(f"{color('[ERR]', RED)} Installation requires root privileges. Try: sudo sh install.sh")


def install() -> None:
    require_root()
    base_dir = Path(__file__).resolve().parent
    src_main = base_dir / "main.py"
    if not src_main.exists():
        raise SystemExit(f"Could not find entry point: {src_main}")

    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    INSTALL_DIR.mkdir(parents=True)
    _copy_tree(base_dir, INSTALL_DIR)

    main_script = INSTALL_DIR / "main.py"
    mode = stat.S_IMODE(main_script.stat().st_mode)
    main_script.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if BIN_PATH.exists() or BIN_PATH.is_symlink():
        BIN_PATH.unlink()
    BIN_PATH.symlink_to(main_script)
    ok(f"Installed lixet -> {main_script}")
    info("Command available as: lixet")


def uninstall() -> None:
    require_root()
    if BIN_PATH.exists() or BIN_PATH.is_symlink():
        BIN_PATH.unlink()
        ok(f"Removed {BIN_PATH}")
    else:
        info(f"{BIN_PATH} is not installed")
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
        ok(f"Removed {INSTALL_DIR}")


def _skip(path: Path) -> bool:
    if path.name in SKIP_DIRS or path.name in SKIP_NAMES:
        return True
    if path.name.endswith(".pyc"):
        return True
    if path.name.endswith(".bak") or ".lixet." in path.name and path.name.endswith(".bak"):
        return True
    if path.name.startswith(".env."):
        return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if _skip(item):
            continue
        target = dst / item.name
        if item.is_dir():
            target.mkdir()
            _copy_tree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)


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

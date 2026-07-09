#!/usr/bin/env python3
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Install or uninstall the global lixet command."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BIN_PATH = Path("/usr/local/bin/lixet")
INSTALL_DIR = Path("/opt/lixet")
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "developer", "docker", "tests"}
SKIP_NAMES = {".env"}
REQUIRED_PATHS = ("VERSION", "main.py", "install.py", "cli", "core", "services", "validators", "repair", "backup", "utils")
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"
RESET = "\033[0m"


def color(text: str, code: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
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
    _validate_tree(base_dir)

    INSTALL_DIR.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".lixet-install-", dir=str(INSTALL_DIR.parent)))
    backup_dir: Path | None = None
    try:
        _copy_tree(base_dir, tmp_dir)
        _validate_tree(tmp_dir)
        _make_executable(tmp_dir / "main.py")

        if INSTALL_DIR.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = INSTALL_DIR.with_name(f".lixet-install-backup-{stamp}")
            shutil.move(INSTALL_DIR, backup_dir)

        shutil.move(tmp_dir, INSTALL_DIR)
        _link_command(INSTALL_DIR / "main.py")
    except Exception as exc:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if INSTALL_DIR.exists():
            shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        if backup_dir and backup_dir.exists():
            shutil.move(backup_dir, INSTALL_DIR)
            try:
                _link_command(INSTALL_DIR / "main.py")
            except OSError:
                pass
        raise SystemExit(f"{color('[ERR]', RED)} Installation failed: {exc}") from exc
    else:
        if backup_dir:
            shutil.rmtree(backup_dir, ignore_errors=True)

    ok(f"Installed lixet -> {INSTALL_DIR / 'main.py'}")
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


def _validate_tree(root: Path) -> None:
    missing = [name for name in REQUIRED_PATHS if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"missing required project files: {', '.join(missing)}")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}(?:-(?:alpha|beta|rc))?", version):
        raise RuntimeError("VERSION must contain a clean semantic version, such as 0.2.0-beta")


def _make_executable(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _link_command(main_script: Path) -> None:
    BIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BIN_PATH.exists() or BIN_PATH.is_symlink():
        BIN_PATH.unlink()
    BIN_PATH.symlink_to(main_script)


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

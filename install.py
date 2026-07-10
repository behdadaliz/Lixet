#!/usr/bin/env python3
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Install or uninstall Lixet through one transactional implementation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core.install_transaction import InstallError, InstallRollbackError, InstallTransaction

BIN_PATH = Path("/usr/local/bin/lixet")
INSTALL_DIR = Path("/opt/lixet")


def require_root() -> None:
    geteuid = getattr(os, "geteuid", lambda: -1)
    if os.name != "posix" or geteuid() != 0:
        raise InstallError("Installation requires Linux root privileges. Try: sudo sh install.sh")


def install(force: bool = False) -> None:
    require_root()
    transaction = InstallTransaction(Path(__file__).resolve().parent, INSTALL_DIR, BIN_PATH, force=force)
    transaction.install()
    print(f"[OK] Installed lixet -> {INSTALL_DIR / 'main.py'}")
    print("[INFO] Command available as: lixet")


def uninstall(force: bool = False) -> None:
    require_root()
    transaction = InstallTransaction(Path(__file__).resolve().parent, INSTALL_DIR, BIN_PATH, force=force)
    transaction.uninstall()
    print("[OK] Lixet uninstalled.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or uninstall Lixet")
    parser.add_argument("action", nargs="?", choices=("install", "uninstall"), default="install")
    parser.add_argument("--force", action="store_true", help="Replace an unowned target after explicit review")
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            install(force=args.force)
        else:
            uninstall(force=args.force)
    except InstallRollbackError as exc:
        print(f"[CRITICAL] Installation rollback failed: {exc}", file=sys.stderr)
        return 5
    except InstallError as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

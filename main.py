#!/usr/bin/env python3
# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Lixet entry point."""

from __future__ import annotations

import sys


def check_python_version() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Lixet requires Python 3.10 or higher.")


def main() -> int:
    check_python_version()
    from cli.parser import parse_and_execute

    try:
        return parse_and_execute(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n[!] Operation cancelled by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

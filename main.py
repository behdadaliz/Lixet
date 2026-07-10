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
    except EOFError:
        from core.models import ExitCode
        from utils.ui import UI

        UI().status("info", "Input ended before an operation was approved.")
        return int(ExitCode.ISSUES)
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        from utils.ui import UI

        print()
        UI().status("info", "Operation cancelled by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

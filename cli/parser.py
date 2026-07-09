# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Command-line interface for Lixet."""

from __future__ import annotations

import argparse
import sys
import textwrap
from difflib import get_close_matches
from functools import partial

from utils.ui import UI


class LixetArgumentParser(argparse.ArgumentParser):
    """Argparse wrapper with normal exit codes and help formatting."""

    def __init__(self, *args, no_color: bool = False, **kwargs) -> None:
        self.ui = UI(no_color=no_color)
        super().__init__(*args, **kwargs)

    def format_help(self) -> str:
        text = super().format_help()
        if not self.ui.color:
            return text
        replacements = {
            "usage:": self.ui.c("usage:", self.ui.BOLD + self.ui.CYAN),
            "positional arguments:": self.ui.c("positional arguments:", self.ui.BOLD + self.ui.CYAN),
            "options:": self.ui.c("options:", self.ui.BOLD + self.ui.CYAN),
            "Common commands:": self.ui.c("Common commands:", self.ui.BOLD + self.ui.CYAN),
            "Available commands:": self.ui.c("Available commands:", self.ui.BOLD + self.ui.CYAN),
            "Supported services:": self.ui.c("Supported services:", self.ui.BOLD + self.ui.CYAN),
            "Lixet - deterministic Linux configuration recovery.": self.ui.c(
                "Lixet - deterministic Linux configuration recovery.",
                self.ui.BOLD,
            ),
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def error(self, message: str) -> None:
        if message.startswith("unrecognized arguments:"):
            unknown = message.split(":", 1)[1].strip().split()[0]
            suggestion = get_close_matches(unknown, ["--version", "--update", "--no-color"], n=1)
            if suggestion:
                self.exit(
                    2,
                    f"{self.ui.c('Unknown option:', self.ui.RED)} {unknown}\n"
                    f"Did you mean: {self.ui.c(suggestion[0], self.ui.BOLD)}?\n",
                )
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {self.ui.c('error:', self.ui.RED)} {message}\n")


def parse_and_execute(args: list[str]) -> int:
    no_color = "--no-color" in args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="Disable colored output")
    parser = LixetArgumentParser(
        prog="lixet",
        parents=[common],
        no_color=no_color,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""
            Lixet - deterministic Linux configuration recovery.

            Available commands:
              lixet                          Show this help page
              lixet --help                   Show this help page
              lixet --version                Show installed Lixet version
              sudo lixet --update            Update the installed Lixet version
              lixet scan <service>           Scan one service and offer safe repairs
              lixet scan <service> --dry-run Preview repairs without changing files
              lixet scan <service> -y        Apply all supported repairs without prompting
              lixet doctor                   Scan all supported services
              lixet doctor --dry-run         Preview all supported repairs
              lixet --no-color ...           Disable colored output

            Supported services:
              ssh, nginx, ufw, dns, networking, systemd
        """),
    )
    parser.add_argument("--update", action="store_true", help="Update the installed Lixet version")
    parser.add_argument("--version", action="store_true", help="Show installed Lixet version")
    subparsers = parser.add_subparsers(dest="command", parser_class=partial(LixetArgumentParser, no_color=no_color))

    scan_parser = subparsers.add_parser("scan", parents=[common], help="Analyze a specific service")
    scan_parser.add_argument("service", help="Service to scan, e.g. ssh")
    scan_parser.add_argument("--config", help="Override service configuration path")
    scan_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    scan_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    doctor_parser = subparsers.add_parser("doctor", parents=[common], help="Run all supported service checks")
    doctor_parser.add_argument("--config", help="Override service configuration path for supported checks")
    doctor_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    doctor_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    if not args:
        parser.print_help()
        return 0

    parsed_args = parser.parse_args(args)
    if parsed_args.update:
        from core.updater import LixetUpdater

        return 0 if LixetUpdater(no_color=getattr(parsed_args, "no_color", False)).run() else 1
    if parsed_args.version:
        from core.version import VersionReporter

        return 0 if VersionReporter(no_color=getattr(parsed_args, "no_color", False)).run() else 1

    if not parsed_args.command:
        parser.print_help()
        return 0

    from core.engine import LixetEngine

    engine = LixetEngine(
        dry_run=parsed_args.dry_run,
        yes=parsed_args.yes,
        config_path=parsed_args.config,
        no_color=getattr(parsed_args, "no_color", False),
    )
    ok = engine.scan_service(parsed_args.service) if parsed_args.command == "scan" else engine.run_doctor()
    return 0 if ok else 1

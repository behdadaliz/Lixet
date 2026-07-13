# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Command-line interface for Lixet."""

from __future__ import annotations

import argparse
import sys
import textwrap
from difflib import get_close_matches
from typing import NoReturn

from core.models import ExitCode
from core.registry import service_names
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

    def error(self, message: str) -> NoReturn:
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
    services = ", ".join(service_names())

    class Subparser(LixetArgumentParser):
        def __init__(self, *sub_args, **sub_kwargs) -> None:
            super().__init__(*sub_args, no_color=no_color, **sub_kwargs)

    common = Subparser(add_help=False)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="Disable colored output")
    parser = LixetArgumentParser(
        prog="lixet",
        parents=[common],
        no_color=no_color,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(f"""
            Lixet - deterministic Linux configuration recovery.

            Commands:
              scan        Scan a service or configuration file
              doctor      Scan supported services
              services    List supported services
              backups     List protected backups
              restore     Restore a protected backup
              uninstall   Remove installed Lixet files while preserving backups

            Common examples:
              lixet scan ssh
              lixet scan /etc/nginx/nginx.conf
              lixet scan custom.conf --type nginx
              lixet doctor
              lixet backups
              lixet restore <backup-id>
              sudo lixet uninstall
              lixet --version
              sudo lixet --update

            Supported services:
              {services}
        """),
    )
    parser.add_argument("--update", action="store_true", help="Update the installed Lixet version")
    parser.add_argument("--version", action="store_true", help="Show installed and latest Lixet version")
    subparsers = parser.add_subparsers(dest="command", parser_class=Subparser)

    scan_parser = subparsers.add_parser("scan", parents=[common], help="Scan a service or configuration file")
    scan_parser.add_argument("target", help="Service, alias, file, or supported directory to scan")
    scan_parser.add_argument("--type", choices=service_names(), help="Explicit configuration type for a path target")
    scan_parser.add_argument("--config", help="Override service configuration path")
    scan_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    scan_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    doctor_parser = subparsers.add_parser("doctor", parents=[common], help="Run all supported service checks")
    doctor_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    doctor_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    subparsers.add_parser("services", parents=[common], help="Show supported services")

    subparsers.add_parser("backups", parents=[common], help="List protected backups")

    restore_parser = subparsers.add_parser("restore", parents=[common], help="Restore a protected backup")
    restore_parser.add_argument("backup_id", help="Backup ID to restore")
    restore_parser.add_argument("--dry-run", action="store_true", help="Preview restore without modifying files")

    uninstall_parser = subparsers.add_parser("uninstall", parents=[common], help="Uninstall Lixet and preserve backups")
    uninstall_parser.add_argument("--dry-run", action="store_true", help="Preview uninstall without removing files")

    if not args:
        parser.print_help()
        return 0

    parsed_args = parser.parse_args(args)
    if parsed_args.update:
        from core.updater import LixetUpdater

        return int(LixetUpdater(no_color=getattr(parsed_args, "no_color", False)).run())
    if parsed_args.version:
        from core.version import VersionReporter

        return int(
            ExitCode.OK
            if VersionReporter(no_color=getattr(parsed_args, "no_color", False)).run()
            else ExitCode.INSPECTION_FAILED
        )

    if not parsed_args.command:
        parser.print_help()
        return 0

    if parsed_args.command == "uninstall":
        from core.uninstaller import LixetUninstaller

        return int(
            LixetUninstaller(
                dry_run=getattr(parsed_args, "dry_run", False),
                no_color=getattr(parsed_args, "no_color", False),
            ).run()
        )

    from core.engine import LixetEngine

    engine = LixetEngine(
        dry_run=getattr(parsed_args, "dry_run", False),
        yes=getattr(parsed_args, "yes", False),
        config_path=getattr(parsed_args, "config", None),
        target_type=getattr(parsed_args, "type", None),
        no_color=getattr(parsed_args, "no_color", False),
    )
    if parsed_args.command == "scan":
        if getattr(parsed_args, "config", None) and not getattr(parsed_args, "type", None):
            return int(engine.scan_service(parsed_args.target))
        return int(engine.scan(parsed_args.target))
    if parsed_args.command == "doctor":
        return int(engine.run_doctor())
    if parsed_args.command == "services":
        return int(engine.show_services())
    if parsed_args.command == "backups":
        return int(engine.show_backups())
    if parsed_args.command == "restore":
        return int(engine.restore_backup(parsed_args.backup_id))
    return int(ExitCode.USAGE)

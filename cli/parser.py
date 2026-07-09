# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Command-line interface for Lixet."""

from __future__ import annotations

import argparse
import textwrap


class LixetArgumentParser(argparse.ArgumentParser):
    """Argparse wrapper with normal exit codes and help formatting."""


def parse_and_execute(args: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="Disable colored output")
    parser = LixetArgumentParser(
        prog="lixet",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""
            Lixet - deterministic Linux configuration recovery.

            Common commands:
              lixet scan ssh
              lixet scan nginx --dry-run
              lixet doctor
        """),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    from core.engine import LixetEngine

    engine = LixetEngine(
        dry_run=parsed_args.dry_run,
        yes=parsed_args.yes,
        config_path=parsed_args.config,
        no_color=getattr(parsed_args, "no_color", False),
    )
    ok = engine.scan_service(parsed_args.service) if parsed_args.command == "scan" else engine.run_doctor()
    return 0 if ok else 1

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Command-line interface for Lixet."""

from __future__ import annotations

import argparse
import textwrap


class LixetArgumentParser(argparse.ArgumentParser):
    """Argparse wrapper with normal exit codes and help formatting."""


def parse_and_execute(args: list[str]) -> int:
    parser = LixetArgumentParser(
        prog="lixet",
        description=textwrap.dedent("""
            Lixet - deterministic configuration recovery and diagnostics.
        """),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Analyze a specific service")
    scan_parser.add_argument("service", help="Service to scan, e.g. ssh")
    scan_parser.add_argument("--config", help="Override service configuration path")
    scan_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    scan_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    doctor_parser = subparsers.add_parser("doctor", help="Run all supported service checks")
    doctor_parser.add_argument("--config", help="Override service configuration path for supported checks")
    doctor_parser.add_argument("--dry-run", action="store_true", help="Preview repairs without modifying files")
    doctor_parser.add_argument("-y", "--yes", action="store_true", help="Apply supported repairs without prompting")

    parsed_args = parser.parse_args(args)
    from core.engine import LixetEngine

    engine = LixetEngine(dry_run=parsed_args.dry_run, yes=parsed_args.yes, config_path=parsed_args.config)
    ok = engine.scan_service(parsed_args.service) if parsed_args.command == "scan" else engine.run_doctor()
    return 0 if ok else 1

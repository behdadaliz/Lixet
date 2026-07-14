# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Small helpers shared by validators."""

from __future__ import annotations

import hashlib
import re

from core.models import RepairLevel
from utils.command import DEFAULT_TIMEOUT, CommandExecutor, CommandRunner

_RUNNER = CommandRunner()


def run_command(args: list[str], timeout: int = DEFAULT_TIMEOUT, runner: CommandExecutor | None = None) -> dict | None:
    return (runner or _RUNNER).run(args, timeout)


def issue(
    code: str,
    severity: str,
    description: str,
    file_path: str,
    fixes: list[dict] | None = None,
    line_number: int | None = None,
    service: str | None = None,
    evidence: str | None = None,
    safety_note: str | None = None,
    source_command: str | None = None,
    repair_level: str | None = None,
    risk_note: str | None = None,
    rollback_note: str | None = None,
    actionable: bool | None = None,
    confidence: str = "high",
    validator_result: str | None = None,
) -> dict:
    level = repair_level or (RepairLevel.SAFE.value if fixes else RepairLevel.REPORT_ONLY.value)
    if level == "report-only":
        level = RepairLevel.REPORT_ONLY.value
    if level not in {item.value for item in RepairLevel}:
        level = RepairLevel.REPORT_ONLY.value
    clean_fixes = fixes or []
    if level == RepairLevel.REPORT_ONLY.value:
        clean_fixes = []
    repairable = bool(clean_fixes) and level in {RepairLevel.SAFE.value, RepairLevel.GUARDED.value}
    identity = "\0".join((service or "", code, file_path, str(line_number or 0), evidence or ""))
    return {
        "id": hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:20],
        "code": code,
        "severity": severity,
        "service": service,
        "description": description,
        "file_path": file_path,
        "line_number": line_number,
        "evidence": evidence,
        "repairable": repairable,
        "repair_level": level,
        "safety_note": safety_note,
        "risk_note": risk_note,
        "rollback_note": rollback_note,
        "source_command": source_command,
        "fixes": clean_fixes,
        "actionable": repairable if actionable is None else actionable,
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
        "validator_result": validator_result,
    }


def first_match(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.MULTILINE)

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Small helpers shared by validators."""

from __future__ import annotations

import re
import shutil
import subprocess


def run_command(args: list[str]) -> dict | None:
    if not shutil.which(args[0]):
        return None
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    evidence = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return {"returncode": result.returncode, "evidence": evidence}


def issue(
    code: str,
    severity: str,
    description: str,
    file_path: str,
    fixes: list[dict] | None = None,
    line_number: int | None = None,
    service: str | None = None,
    evidence: str | None = None,
) -> dict:
    return {
        "id": code,
        "code": code,
        "severity": severity,
        "service": service,
        "description": description,
        "file_path": file_path,
        "line_number": line_number,
        "evidence": evidence,
        "fixes": fixes or [],
    }


def first_match(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.MULTILINE)

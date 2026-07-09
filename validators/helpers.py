# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Small helpers shared by validators."""

from __future__ import annotations

import re
import shutil
import subprocess


DEFAULT_TIMEOUT = 5


def run_command(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    if not shutil.which(args[0]):
        return None
    try:
        result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout)
        evidence = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return {"returncode": result.returncode, "evidence": evidence, "command": " ".join(args), "timeout": False}
    except subprocess.TimeoutExpired as exc:
        evidence = f"Command timed out after {timeout}s: {' '.join(args)}"
        if exc.stdout:
            evidence += f"\n{str(exc.stdout).strip()}"
        if exc.stderr:
            evidence += f"\n{str(exc.stderr).strip()}"
        return {"returncode": 124, "evidence": evidence, "command": " ".join(args), "timeout": True}
    except OSError as exc:
        evidence = f"Could not run command {' '.join(args)}: {exc}"
        return {"returncode": 126, "evidence": evidence, "command": " ".join(args), "timeout": False}


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
) -> dict:
    repairable = bool(fixes)
    return {
        "id": code,
        "code": code,
        "severity": severity,
        "service": service,
        "description": description,
        "file_path": file_path,
        "line_number": line_number,
        "evidence": evidence,
        "repairable": repairable,
        "safety_note": safety_note,
        "source_command": source_command,
        "fixes": fixes or [],
    }


def first_match(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.MULTILINE)

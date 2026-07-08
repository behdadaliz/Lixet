# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Small helpers shared by validators."""

from __future__ import annotations


def issue(
    code: str,
    severity: str,
    description: str,
    file_path: str,
    fixes: list[dict] | None = None,
    line_number: int | None = None,
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "description": description,
        "file_path": file_path,
        "line_number": line_number,
        "fixes": fixes or [],
    }

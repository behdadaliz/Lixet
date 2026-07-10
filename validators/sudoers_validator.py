# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""sudoers diagnostics using visudo as the authoritative parser."""

from __future__ import annotations

import re
from pathlib import Path

from validators.helpers import issue


class SudoersValidator:
    ERROR_PATTERNS = (
        re.compile(r"(?P<file>(?:[A-Za-z]:)?[^:\n]+):(?P<line>\d+):"),
        re.compile(r"(?P<file>(?:[A-Za-z]:)?\S+)\s+near line\s+(?P<line>\d+)", re.I),
    )

    def __init__(self, file_path: str = "/etc/sudoers") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        test = data.get("config_test")
        if not test:
            return [
                self._make(
                    "SUDOERS_VERIFIER_UNAVAILABLE", "info", "visudo is unavailable; sudoers validation was not run."
                )
            ]
        if test.get("returncode") == 0:
            return []
        evidence = str(test.get("evidence") or "visudo failed without output.")
        file_path, line_number = self._location(evidence)
        row = self._find_row(data.get("files", []), file_path, line_number)
        fixes: list[dict] = []
        level = "unsafe"
        risk = (
            "Never edit the main sudoers file automatically. Use visudo and keep another administrative session open."
        )
        if row and self._included_file(file_path):
            fixes = [
                {
                    "action": "comment_out_with_reason",
                    "line_number": row["line_number"],
                    "expected_original": row["raw_line"],
                    "reason": "Lixet disabled line rejected by visudo",
                }
            ]
            level = "guarded"
            risk = "This disables one included sudoers rule. Confirm another administrative path before approval."
        return [
            self._make(
                "SUDOERS_CONFIG_TEST_FAILED",
                "critical",
                "visudo rejected the sudoers configuration.",
                row,
                file_path,
                evidence,
                test.get("command"),
                fixes,
                level,
                risk,
            )
        ]

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        path: str | None = None,
        evidence: str | None = None,
        command: str | None = None,
        fixes: list[dict] | None = None,
        level: str = "unsafe",
        risk: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            path or self.file_path,
            fixes,
            int(row["line_number"]) if row else None,
            "sudoers",
            evidence,
            "The main sudoers file is never repaired automatically.",
            command,
            level,
            risk,
            "A protected backup is restored if visudo validation fails." if fixes else None,
        )

    def _location(self, evidence: str) -> tuple[str, int | None]:
        for pattern in self.ERROR_PATTERNS:
            match = pattern.search(evidence)
            if match:
                return match.group("file"), int(match.group("line"))
        return self.file_path, None

    @staticmethod
    def _find_row(files: list[dict], path: str, line: int | None) -> dict | None:
        if line is None:
            return None
        for file_data in files:
            if str(file_data.get("file_path")) != path:
                continue
            for row in file_data.get("lines", []):
                if int(row.get("line_number") or 0) == line:
                    return row
        return None

    @staticmethod
    def _included_file(path: str) -> bool:
        candidate = Path(path)
        return "sudoers.d" in candidate.parts and "." not in candidate.name and not candidate.name.endswith("~")

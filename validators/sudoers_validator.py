# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic sudoers validator."""

from __future__ import annotations

from pathlib import Path

from validators.helpers import first_match, issue


class SudoersValidator:
    def __init__(self, file_path: str = "/etc/sudoers") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        test = data.get("config_test")
        if not test:
            issues.append(issue(
                "SUDOERS_VISUDO_MISSING",
                "info",
                "visudo is not available; sudoers syntax validation was skipped.",
                self.file_path,
                [],
                None,
                "sudoers",
                None,
                "No automatic repair is applied.",
                None,
                "unsafe",
            ))
            return issues
        if test["returncode"] == 0:
            return issues

        evidence = test.get("evidence") or "visudo validation failed without output."
        file_path = self.file_path
        line_number = None
        match = first_match(r"(?P<file>/[^\s:]+):(?P<line>\d+):", evidence)
        if match:
            file_path = match.group("file")
            line_number = int(match.group("line"))

        fixes: list[dict] = []
        level = "unsafe"
        risk = "Breaking sudoers can lock administrators out. Most sudoers repairs are report-only."
        if line_number and self._safe_sudoers_d_line(file_path, line_number):
            fixes = [{
                "action": "comment_out_with_reason",
                "line_number": line_number,
                "reason": "Lixet disabled sudoers line rejected by visudo",
            }]
            level = "guarded"
            risk = "This comments out a sudoers.d line rejected by visudo. Confirm another admin path first."

        issues.append(issue(
            "SUDOERS_CONFIG_TEST_FAILED",
            "critical",
            "sudoers validation failed.",
            file_path,
            fixes,
            line_number,
            "sudoers",
            evidence,
            "No automatic repair is applied unless an exact sudoers.d line can be commented safely.",
            test.get("command"),
            level,
            risk,
            "A backup is restored automatically if visudo verification fails.",
        ))
        return issues

    @staticmethod
    def _safe_sudoers_d_line(file_path: str, line_number: int) -> bool:
        path = Path(file_path)
        if "sudoers.d" not in path.parts or not path.exists() or not path.is_file():
            return False
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return False
        if line_number < 1 or line_number > len(lines):
            return False
        text = lines[line_number - 1].strip()
        return bool(text and not text.startswith("#"))

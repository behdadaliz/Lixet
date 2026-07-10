# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Read-only fstab diagnostics backed by findmnt --verify."""

from __future__ import annotations

import re

from validators.helpers import issue


class FstabValidator:
    FIELD_RE = re.compile(r"(?:\\[0-7]{3}|\\.|[^\s])+")

    def __init__(self, file_path: str = "/etc/fstab") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        verify = data.get("findmnt_verify")
        if verify is None:
            issues.append(
                self._make(
                    "FSTAB_VERIFIER_UNAVAILABLE",
                    "info",
                    "findmnt is unavailable; authoritative fstab validation was not run.",
                )
            )
        elif verify.get("returncode") != 0:
            issues.append(
                self._make(
                    "FSTAB_VERIFY_FAILED",
                    "high",
                    "findmnt reports fstab validation problems.",
                    evidence=verify.get("evidence") or "findmnt failed without output.",
                    command=verify.get("command"),
                )
            )

        seen_mounts: set[str] = set()
        for row in [item for item in data.get("lines", []) if item.get("is_active")]:
            fields = self.FIELD_RE.findall(str(row.get("text") or ""))
            if len(fields) < 4:
                issues.append(
                    self._make(
                        "FSTAB_MISSING_FIELDS",
                        "high",
                        "fstab entry has fewer than four required fields.",
                        row,
                        str(row.get("text") or ""),
                    )
                )
                continue
            mountpoint = fields[1]
            if mountpoint in seen_mounts:
                issues.append(
                    self._make(
                        "FSTAB_DUPLICATE_MOUNTPOINT",
                        "medium",
                        f"Duplicate fstab mountpoint '{mountpoint}'.",
                        row,
                        str(row.get("text") or ""),
                    )
                )
            seen_mounts.add(mountpoint)
            for index, name in ((4, "dump"), (5, "pass")):
                if len(fields) > index and not self._nonnegative_integer(fields[index]):
                    issues.append(
                        self._make(
                            "FSTAB_INVALID_NUMERIC_FIELD",
                            "medium",
                            f"fstab {name} field is not a non-negative integer.",
                            row,
                            fields[index],
                        )
                    )
        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        evidence: str | None = None,
        command: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            str(row.get("file_path")) if row else self.file_path,
            [],
            int(row["line_number"]) if row else None,
            "fstab",
            evidence,
            "fstab changes are report-only; Lixet never runs mount -a.",
            command,
            "unsafe",
        )

    @staticmethod
    def _nonnegative_integer(value: str) -> bool:
        try:
            return int(value) >= 0
        except ValueError:
            return False

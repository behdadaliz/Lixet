# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Read-only sysctl layering and value diagnostics."""

from __future__ import annotations

import re

from validators.helpers import issue


class SysctlValidator:
    INT_KEYS = {"net.ipv4.ip_forward", "net.ipv6.conf.all.forwarding", "vm.swappiness", "fs.file-max"}

    def __init__(self, file_path: str = "/etc/sysctl.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        assignments: dict[str, list[dict]] = {}
        for file_data in data.get("files", []):
            path = str(file_data["file_path"])
            order = int(file_data.get("load_order") or 0)
            for row in file_data.get("lines", []):
                if not row.get("is_active"):
                    continue
                parsed = self._parse(str(row.get("text") or ""))
                if not parsed:
                    issues.append(
                        self._make(
                            "SYSCTL_MALFORMED_LINE",
                            "medium",
                            "Malformed sysctl assignment.",
                            path,
                            row,
                            str(row.get("text") or ""),
                        )
                    )
                    continue
                key, value = parsed
                item = {"path": path, "order": order, "line": int(row["line_number"]), "value": value, "row": row}
                assignments.setdefault(key, []).append(item)
                if key in self.INT_KEYS and value and not self._integer(value):
                    issues.append(
                        self._make(
                            "SYSCTL_INVALID_INTEGER",
                            "medium",
                            f"sysctl key '{key}' expects an integer value.",
                            path,
                            row,
                            value,
                        )
                    )

        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        path: str,
        row: dict | None = None,
        evidence: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            path,
            [],
            int(row["line_number"]) if row else None,
            "sysctl",
            evidence,
            "sysctl overrides are report-only and values are never applied to the running kernel.",
            None,
            "unsafe",
        )

    @staticmethod
    def _parse(text: str) -> tuple[str, str] | None:
        match = re.match(r"^-?([A-Za-z0-9_./*-]+)\s*(?:=|\s)\s*(.*?)\s*$", text)
        if not match or not match.group(1) or not match.group(2):
            return None
        return match.group(1), match.group(2)

    @staticmethod
    def _integer(value: str) -> bool:
        try:
            int(value)
            return True
        except ValueError:
            return False

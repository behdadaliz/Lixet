# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic sysctl configuration validator."""

from __future__ import annotations

import re

from validators.helpers import issue


class SysctlValidator:
    INT_KEYS = {
        "net.ipv4.ip_forward",
        "net.ipv6.conf.all.forwarding",
        "vm.swappiness",
        "fs.file-max",
    }

    def __init__(self, file_path: str = "/etc/sysctl.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        seen: dict[str, tuple[str, int]] = {}
        for file_data in data["files"]:
            path = file_data["file_path"]
            for row in file_data["lines"]:
                if not row["is_active"]:
                    continue
                text = row["text"]
                if "=" not in text:
                    match = re.match(r"^([A-Za-z0-9_.-]+)\s+(.+)$", text)
                    if match:
                        key, value = match.groups()
                        issues.append(issue(
                            "SYSCTL_MISSING_EQUALS",
                            "medium",
                            "sysctl setting uses whitespace instead of '='.",
                            path,
                            [{"action": "replace", "line_number": row["line_number"], "content": f"{key} = {value.strip()}"}],
                            row["line_number"],
                            "sysctl",
                            text,
                            "This rewrites a simple key/value line into sysctl.conf format.",
                            None,
                            "guarded",
                            "Changing sysctl configuration can affect kernel behavior when applied.",
                        ))
                    else:
                        issues.append(issue("SYSCTL_MALFORMED_LINE", "medium", "Malformed sysctl line.", path, [], row["line_number"], "sysctl", text, "No automatic repair is available.", None, "unsafe"))
                    continue

                key, value = [part.strip() for part in text.split("=", 1)]
                if not key:
                    issues.append(issue("SYSCTL_EMPTY_KEY", "high", "sysctl key is empty.", path, [], row["line_number"], "sysctl", text, "No automatic repair is available.", None, "unsafe"))
                    continue
                if key in seen:
                    issues.append(issue(
                        "SYSCTL_DUPLICATE_KEY",
                        "low",
                        f"Duplicate sysctl key '{key}'.",
                        path,
                        [{"action": "comment_out_with_reason", "line_number": row["line_number"], "reason": "Lixet disabled duplicate sysctl key"}],
                        row["line_number"],
                        "sysctl",
                        text,
                        "The later duplicate can be commented out while keeping the first value.",
                        None,
                        "safe",
                    ))
                else:
                    seen[key] = (path, row["line_number"])
                if key in self.INT_KEYS and value and not self._integer(value):
                    issues.append(issue(
                        "SYSCTL_INVALID_INTEGER",
                        "medium",
                        f"sysctl key '{key}' expects an integer value.",
                        path,
                        [],
                        row["line_number"],
                        "sysctl",
                        text,
                        "No automatic value repair is applied.",
                        None,
                        "unsafe",
                    ))
        return issues

    @staticmethod
    def _integer(value: str) -> bool:
        try:
            int(value)
            return True
        except ValueError:
            return False

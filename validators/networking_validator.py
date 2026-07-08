# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic hosts file validator."""

from __future__ import annotations

from validators.helpers import issue


class NetworkingValidator:
    def __init__(self, file_path: str = "/etc/hosts") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        self._check_ipv4_localhost(rows, issues)
        self._check_ipv6_localhost(rows, issues)
        return issues

    def _issue(self, code: str, severity: str, desc: str, fixes: list[dict] | None = None, line: int | None = None) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line)

    def _active_hosts(self, rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            if not row["is_active"]:
                continue
            parts = row["text"].split()
            if len(parts) >= 2:
                out.append({**row, "addr": parts[0], "names": parts[1:]})
        return out

    def _check_ipv4_localhost(self, rows: list[dict], issues: list[dict]) -> None:
        items = [row for row in self._active_hosts(rows) if row["addr"] == "127.0.0.1"]
        if not items:
            issues.append(self._issue("NET_MISSING_IPV4_LOCALHOST", "high", "Missing 127.0.0.1 localhost entry.", [{"action": "append", "content": "127.0.0.1 localhost"}]))
            return
        first = items[0]
        if "localhost" not in first["names"]:
            names = " ".join(first["names"] + ["localhost"])
            issues.append(self._issue(
                "NET_IPV4_LOCALHOST_NAME_MISSING",
                "high",
                "127.0.0.1 entry does not contain localhost.",
                [{"action": "replace", "line_number": first["line_number"], "content": f"127.0.0.1 {names}"}],
                first["line_number"],
            ))

    def _check_ipv6_localhost(self, rows: list[dict], issues: list[dict]) -> None:
        items = [row for row in self._active_hosts(rows) if row["addr"] == "::1"]
        if not items:
            issues.append(self._issue("NET_MISSING_IPV6_LOCALHOST", "medium", "Missing ::1 localhost entry.", [{"action": "append", "content": "::1 localhost ip6-localhost ip6-loopback"}]))

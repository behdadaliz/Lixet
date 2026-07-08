# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic systemd unit validator."""

from __future__ import annotations

from pathlib import Path

from validators.helpers import issue


class SystemdValidator:
    RESTART = {"no", "always", "on-success", "on-failure", "on-abnormal", "on-watchdog", "on-abort"}
    TYPES = {"simple", "exec", "forking", "oneshot", "dbus", "notify", "notify-reload", "idle"}

    def __init__(self, file_path: str = "/etc/systemd/system") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        for unit in data["units"]:
            self._check_unit(unit, issues)
        return issues

    def _issue(self, code: str, severity: str, desc: str, path: str, fixes: list[dict] | None = None, line: int | None = None) -> dict:
        return issue(code, severity, desc, path, fixes, line)

    def _check_unit(self, unit: dict, issues: list[dict]) -> None:
        path = unit["file_path"]
        rows = unit["lines"]
        sections = {row["section"] for row in rows if row["section"]}
        service_rows = [row for row in rows if row["section"] == "Service"]

        if "Unit" not in sections:
            issues.append(self._issue("SYSTEMD_MISSING_UNIT_SECTION", "medium", "Service file is missing [Unit] section.", path))
        if "Service" not in sections:
            issues.append(self._issue("SYSTEMD_MISSING_SERVICE_SECTION", "high", "Service file is missing [Service] section.", path))
            return

        self._check_service_keys(path, service_rows, issues)

    def _check_service_keys(self, path: str, rows: list[dict], issues: list[dict]) -> None:
        exec_rows = [row for row in rows if row["key"] == "ExecStart"]
        if not exec_rows:
            issues.append(self._issue("SYSTEMD_MISSING_EXECSTART", "high", "Service has no ExecStart.", path))
        for row in exec_rows:
            value = row["value"]
            if not value:
                issues.append(self._issue("SYSTEMD_EMPTY_EXECSTART", "high", "ExecStart is empty.", path, [], row["line_number"]))
            cmd = self._cmd(value)
            if cmd and cmd.startswith("/") and not Path(cmd).exists():
                issues.append(self._issue("SYSTEMD_EXECSTART_NOT_FOUND", "high", f"ExecStart binary does not exist: {cmd}", path, [], row["line_number"]))

        for row in [row for row in rows if row["key"] == "Restart"]:
            value = row["value"].lower()
            if value not in self.RESTART:
                issues.append(self._issue(
                    "SYSTEMD_INVALID_RESTART",
                    "medium",
                    f"Invalid Restart value '{row['value']}'.",
                    path,
                    [{"action": "replace", "line_number": row["line_number"], "content": "Restart=no"}],
                    row["line_number"],
                ))

        for row in [row for row in rows if row["key"] == "Type"]:
            value = row["value"].lower()
            if value not in self.TYPES:
                issues.append(self._issue(
                    "SYSTEMD_INVALID_TYPE",
                    "medium",
                    f"Invalid Type value '{row['value']}'.",
                    path,
                    [{"action": "replace", "line_number": row["line_number"], "content": "Type=simple"}],
                    row["line_number"],
                ))

    @staticmethod
    def _cmd(value: str) -> str:
        value = value.strip()
        while value[:1] in {"-", "@", "+", "!"}:
            value = value[1:]
        return value.split(None, 1)[0] if value else ""

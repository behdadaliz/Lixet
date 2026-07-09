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
        self._check_system(data, issues)
        for unit in data["units"]:
            self._check_unit(unit, issues)
        return issues

    def _issue(
        self,
        code: str,
        severity: str,
        desc: str,
        path: str,
        fixes: list[dict] | None = None,
        line: int | None = None,
        repair_level: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        return issue(code, severity, desc, path, fixes, line, "systemd", None, None, None, repair_level, risk_note)

    def _check_system(self, data: dict, issues: list[dict]) -> None:
        failed = data.get("failed_units")
        state = data.get("system_state")
        if not failed:
            issues.append(issue("SYSTEMD_COMMAND_MISSING", "info", "systemctl is not available; runtime systemd checks were skipped.", self.file_path, [], None, "systemd"))
            return
        if state:
            state_text = (state.get("evidence") or "").strip()
            state_low = state_text.lower()
            if "degraded" in state_low:
                issues.append(issue(
                    "SYSTEMD_DEGRADED",
                    "medium",
                    "systemd is running in degraded state.",
                    self.file_path,
                    [],
                    None,
                    "systemd",
                    state_text or "degraded",
                    "No automatic systemd repair is applied.",
                    state.get("command"),
                ))
            elif state["returncode"] != 0:
                issues.append(issue(
                    "SYSTEMD_UNAVAILABLE",
                    "info",
                    "systemd runtime state is unavailable in this environment.",
                    self.file_path,
                    [],
                    None,
                    "systemd",
                    state_text or "systemctl is-system-running failed.",
                    "No automatic systemd repair is applied.",
                    state.get("command"),
                ))
        if failed["returncode"] != 0:
            issues.append(issue(
                "SYSTEMD_FAILED_UNITS_CHECK_FAILED",
                "low",
                "Could not inspect failed systemd units.",
                self.file_path,
                [],
                None,
                "systemd",
                failed.get("evidence") or "systemctl --failed failed.",
                "No automatic systemd repair is applied.",
                failed.get("command"),
            ))
            return
        evidence = failed.get("evidence", "")
        if failed["returncode"] == 0 and "0 loaded units listed" not in evidence.lower() and "failed" in evidence.lower():
            issues.append(issue("SYSTEMD_FAILED_UNITS", "medium", "systemctl reports failed units.", self.file_path, [], None, "systemd", evidence, "No automatic restart is performed.", failed.get("command")))

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
                    repair_level="safe",
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
                    repair_level="guarded",
                    risk_note="Changing systemd Type can affect how the service process is tracked.",
                ))

    @staticmethod
    def _cmd(value: str) -> str:
        value = value.strip()
        while value[:1] in {"-", "@", "+", "!"}:
            value = value[1:]
        return value.split(None, 1)[0] if value else ""

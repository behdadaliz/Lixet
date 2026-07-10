# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Conservative systemd runtime and unit diagnostics."""

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
        self._check_runtime(data, issues)
        self._check_config_test(data, issues)
        for unit in data.get("units", []):
            self._check_unit(unit, issues)
        return issues

    def _check_config_test(self, data: dict, issues: list[dict]) -> None:
        if not data.get("units"):
            return
        result = data.get("config_test")
        if result is None:
            issues.append(
                self._make(
                    "SYSTEMD_VERIFIER_UNAVAILABLE",
                    "info",
                    "systemd-analyze is unavailable; authoritative unit validation was not run.",
                )
            )
        elif result.get("returncode") != 0:
            issues.append(
                self._make(
                    "SYSTEMD_VERIFY_FAILED",
                    "high",
                    "systemd-analyze rejected one or more local units.",
                    evidence=result.get("evidence") or "systemd-analyze failed without output.",
                    command=result.get("command"),
                )
            )

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        path: str | None = None,
        row: dict | None = None,
        evidence: str | None = None,
        command: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            path or self.file_path,
            [],
            int(row["line_number"]) if row else None,
            "systemd",
            evidence,
            "Service behavior changes are report-only; verify units with systemd-analyze before manual edits.",
            command,
            "unsafe",
        )

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        failed = data.get("failed_units")
        state = data.get("system_state")
        if not failed and not state:
            issues.append(
                self._make(
                    "SYSTEMD_COMMAND_UNAVAILABLE",
                    "info",
                    "systemctl is unavailable; runtime systemd checks were not run.",
                )
            )
            return
        if state:
            evidence = str(state.get("evidence") or "").strip()
            if "degraded" in evidence.lower():
                issues.append(
                    self._make(
                        "SYSTEMD_DEGRADED",
                        "medium",
                        "systemd reports a degraded system state.",
                        evidence=evidence,
                        command=state.get("command"),
                    )
                )
            elif state.get("returncode") != 0:
                issues.append(
                    self._make(
                        "SYSTEMD_RUNTIME_UNAVAILABLE",
                        "info",
                        "systemd runtime state is unavailable in this environment.",
                        evidence=evidence,
                        command=state.get("command"),
                    )
                )
        if failed:
            evidence = str(failed.get("evidence") or "")
            if failed.get("returncode") != 0:
                issues.append(
                    self._make(
                        "SYSTEMD_FAILED_UNITS_CHECK_FAILED",
                        "low",
                        "Could not inspect failed systemd units.",
                        evidence=evidence,
                        command=failed.get("command"),
                    )
                )
            elif "0 loaded units listed" not in evidence.lower() and "failed" in evidence.lower():
                issues.append(
                    self._make(
                        "SYSTEMD_FAILED_UNITS",
                        "medium",
                        "systemctl reports failed units.",
                        evidence=evidence,
                        command=failed.get("command"),
                    )
                )

    def _check_unit(self, unit: dict, issues: list[dict]) -> None:
        path = str(unit["file_path"])
        rows = unit.get("lines", [])
        service_rows = [row for row in rows if row.get("section") == "Service"]
        sections = {row.get("section") for row in rows if row.get("section")}
        if "Service" not in sections:
            issues.append(
                self._make("SYSTEMD_MISSING_SERVICE_SECTION", "high", "Service unit has no [Service] section.", path)
            )
            return

        type_rows = [row for row in service_rows if row.get("key") == "Type"]
        service_type = str(type_rows[-1].get("value") or "simple").lower() if type_rows else "simple"
        exec_rows = [row for row in service_rows if row.get("key") == "ExecStart"]
        if not exec_rows and service_type != "oneshot":
            issues.append(
                self._make("SYSTEMD_MISSING_EXECSTART", "high", "Non-oneshot service has no ExecStart.", path)
            )
        for row in exec_rows:
            value = str(row.get("value") or "")
            if not value:
                issues.append(self._make("SYSTEMD_EMPTY_EXECSTART", "high", "ExecStart is empty.", path, row))
                continue
            command = self._command(value)
            if command.startswith("/") and "%" not in command and "$" not in command and not Path(command).exists():
                issues.append(
                    self._make(
                        "SYSTEMD_EXECSTART_NOT_FOUND",
                        "high",
                        f"ExecStart executable does not exist: {command}",
                        path,
                        row,
                    )
                )
        for row in [item for item in service_rows if item.get("key") == "Restart"]:
            value = str(row.get("value") or "").lower()
            if value not in self.RESTART:
                issues.append(
                    self._make("SYSTEMD_INVALID_RESTART", "medium", f"Invalid Restart value '{value}'.", path, row)
                )
        for row in type_rows:
            value = str(row.get("value") or "").lower()
            if value not in self.TYPES:
                issues.append(self._make("SYSTEMD_INVALID_TYPE", "medium", f"Invalid Type value '{value}'.", path, row))

    @staticmethod
    def _command(value: str) -> str:
        value = value.strip()
        while value[:1] in {"-", "@", ":", "+", "!"}:
            value = value[1:]
        return value.split(None, 1)[0] if value else ""

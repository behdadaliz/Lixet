# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Read-only UFW policy and runtime diagnostics."""

from __future__ import annotations

import re

from validators.helpers import issue


class UFWValidator:
    POLICIES = {"DEFAULT_INPUT_POLICY", "DEFAULT_OUTPUT_POLICY", "DEFAULT_FORWARD_POLICY"}

    def __init__(self, file_path: str = "/etc/ufw/ufw.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        self._runtime(data.get("ufw_status"), issues)
        files = data.get("files") or [{"file_path": self.file_path, "role": "state", "lines": data.get("lines", [])}]
        if data.get("missing_config"):
            if not any(item["code"] == "UFW_NOT_INSTALLED" for item in issues):
                issues.append(self._make("UFW_CONFIG_NOT_FOUND", "medium", "UFW state configuration was not found."))
            return issues
        for file_data in files:
            role = file_data.get("role")
            rows = file_data.get("lines", [])
            path = str(file_data.get("file_path") or self.file_path)
            if role == "state":
                self._setting(rows, path, "ENABLED", {"yes", "no"}, issues)
            elif role == "defaults":
                self._setting(rows, path, "IPV6", {"yes", "no"}, issues)
                for key in sorted(self.POLICIES):
                    self._setting(rows, path, key, {"ACCEPT", "DROP", "REJECT"}, issues, upper=True)
        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        path: str | None = None,
        evidence: str | None = None,
        command: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            path or (str(row.get("file_path")) if row else self.file_path),
            [],
            int(row["line_number"]) if row else None,
            "ufw",
            evidence,
            "UFW startup, IPv6, policy, and rule changes are report-only.",
            command,
            "unsafe",
        )

    def _runtime(self, result: dict | None, issues: list[dict]) -> None:
        if not result:
            issues.append(
                self._make("UFW_NOT_INSTALLED", "info", "ufw is unavailable; runtime firewall checks were not run.")
            )
            return
        evidence = str(result.get("evidence") or "")
        if result.get("returncode") != 0:
            issues.append(
                self._make(
                    "UFW_STATUS_FAILED",
                    "low",
                    "Could not read UFW runtime status.",
                    evidence=evidence,
                    command=result.get("command"),
                )
            )
        elif "status: inactive" in evidence.lower():
            return
        elif "status: active" in evidence.lower() and not re.search(
            r"\bopenssh\b|\b22/tcp\b|(^|\s)22(\s|/)", evidence, re.I | re.M
        ):
            issues.append(
                self._make(
                    "UFW_SSH_NOT_ALLOWED",
                    "high",
                    "UFW is active, but no obvious SSH allow rule was found.",
                    evidence=evidence,
                    command=result.get("command"),
                )
            )

    def _setting(
        self, rows: list[dict], path: str, key: str, valid: set[str], issues: list[dict], upper: bool = False
    ) -> None:
        items = []
        for row in rows:
            text = str(row.get("text") or "")
            if not row.get("is_active") or "=" not in text:
                continue
            name, value = text.split("=", 1)
            if name.strip() == key:
                items.append({**row, "value": value.strip().strip("'\"")})
        if not items:
            issues.append(
                self._make(
                    f"UFW_MISSING_{key}", "low", f"{key} is not explicitly configured in its expected file.", path=path
                )
            )
            return
        normalized = (lambda value: value.upper()) if upper else (lambda value: value.lower())
        effective = items[-1]
        if normalized(str(effective["value"])) not in valid:
            issues.append(
                self._make(
                    f"UFW_INVALID_{key}",
                    "medium",
                    f"Effective {key} value '{effective['value']}' is invalid.",
                    effective,
                    path,
                )
            )
        return

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic UFW configuration validator."""

from __future__ import annotations

import re

from validators.helpers import issue


class UFWValidator:
    POLICIES = {
        "DEFAULT_INPUT_POLICY": "DROP",
        "DEFAULT_OUTPUT_POLICY": "ACCEPT",
        "DEFAULT_FORWARD_POLICY": "DROP",
    }

    def __init__(self, file_path: str = "/etc/ufw/ufw.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        self._check_runtime_status(data, issues)
        if data.get("missing_config"):
            if not any(item.get("code") == "UFW_NOT_INSTALLED" for item in issues):
                issues.append(issue(
                    "UFW_CONFIG_NOT_FOUND",
                    "medium",
                    "UFW configuration file was not found.",
                    self.file_path,
                    [],
                    None,
                    "ufw",
                    "The configured ufw.conf path does not exist.",
                    "No automatic firewall repair is applied.",
                ))
            return issues
        self._check_bool(rows, issues, "ENABLED", "no", required=True)
        self._check_bool(rows, issues, "IPV6", "yes", required=False)
        self._check_policies(rows, issues)
        return issues

    def _issue(
        self,
        code: str,
        severity: str,
        desc: str,
        fixes: list[dict] | None = None,
        line: int | None = None,
        repair_level: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line, "ufw", None, None, None, repair_level, risk_note)

    def _check_runtime_status(self, data: dict, issues: list[dict]) -> None:
        status = data.get("ufw_status")
        if not status:
            issues.append(self._issue("UFW_NOT_INSTALLED", "info", "ufw command is not available on this system.", repair_level="unsafe"))
            return
        evidence = status.get("evidence", "")
        if status["returncode"] != 0:
            issues.append(issue("UFW_STATUS_FAILED", "low", "Could not read UFW runtime status.", self.file_path, [], None, "ufw", evidence, "No safe automatic repair available.", status.get("command"), "unsafe"))
            return
        low = evidence.lower()
        if "status: inactive" in low:
            issues.append(issue("UFW_INACTIVE", "info", "UFW is inactive. No repair needed unless you intend to enable the firewall.", self.file_path, [], None, "ufw", evidence, "No repair needed unless you intend to enable the firewall.", status.get("command"), "unsafe"))
            return
        if "status: active" in low and not self._ssh_allowed(low):
            issues.append(issue("UFW_SSH_NOT_ALLOWED", "high", "UFW is active, but no obvious SSH allow rule was found.", self.file_path, [], None, "ufw", evidence, "Firewall changes can affect remote access. Add an SSH allow rule manually after review.", status.get("command"), "unsafe", "Automatic firewall command repairs are intentionally disabled because they are not safely reversible."))

    @staticmethod
    def _ssh_allowed(text: str) -> bool:
        return bool(re.search(r"\bopenssh\b|\b22/tcp\b|(^|\s)22(\s|/)", text, re.IGNORECASE | re.MULTILINE))

    def _items(self, rows: list[dict], key: str) -> list[dict]:
        out = []
        for row in rows:
            if not row["is_active"] or "=" not in row["text"]:
                continue
            name, val = row["text"].split("=", 1)
            if name.strip() == key:
                out.append({**row, "value": val.strip().strip('"').strip("'")})
        return out

    def _check_bool(self, rows: list[dict], issues: list[dict], key: str, default: str, required: bool) -> None:
        items = self._items(rows, key)
        if required and not items:
            level = "guarded" if key == "ENABLED" else "safe"
            issues.append(self._issue(f"UFW_MISSING_{key}", "medium", f"Missing {key}; defaulting to {default}.", [{"action": "append", "content": f"{key}={default}"}], repair_level=level, risk_note="Changing ENABLED can affect firewall startup behavior." if level == "guarded" else None))
            return
        for dup in items[1:]:
            issues.append(self._issue(f"UFW_DUPLICATE_{key}", "low", f"Duplicate {key} setting.", [{"action": "comment_out_with_reason", "line_number": dup["line_number"], "reason": "Lixet disabled duplicate UFW setting"}], dup["line_number"], repair_level="safe"))
        for item in items[:1]:
            if item["value"].lower() not in {"yes", "no"}:
                level = "guarded" if key == "ENABLED" else "safe"
                issues.append(self._issue(
                    f"UFW_INVALID_{key}",
                    "medium",
                    f"Invalid {key} value '{item['value']}'. Expected yes or no.",
                    [{"action": "replace", "line_number": item["line_number"], "content": f"{key}={default}"}],
                    item["line_number"],
                    repair_level=level,
                    risk_note="Changing ENABLED can affect firewall startup behavior." if level == "guarded" else None,
                ))

    def _check_policies(self, rows: list[dict], issues: list[dict]) -> None:
        valid = {"ACCEPT", "DROP", "REJECT"}
        for key, default in self.POLICIES.items():
            for item in self._items(rows, key)[:1]:
                value = item["value"].upper()
                if value not in valid:
                    issues.append(self._issue(
                        f"UFW_INVALID_{key}",
                        "medium",
                        f"Invalid {key} value '{item['value']}'.",
                        [{"action": "replace", "line_number": item["line_number"], "content": f'{key}="{default}"'}],
                        item["line_number"],
                        repair_level="safe",
                    ))

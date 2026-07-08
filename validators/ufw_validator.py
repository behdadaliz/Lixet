# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic UFW configuration validator."""

from __future__ import annotations

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
        self._check_bool(rows, issues, "ENABLED", "no", required=True)
        self._check_bool(rows, issues, "IPV6", "yes", required=False)
        self._check_policies(rows, issues)
        return issues

    def _issue(self, code: str, severity: str, desc: str, fixes: list[dict] | None = None, line: int | None = None) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line)

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
            issues.append(self._issue(f"UFW_MISSING_{key}", "medium", f"Missing {key}; defaulting to {default}.", [{"action": "append", "content": f"{key}={default}"}]))
            return
        for dup in items[1:]:
            issues.append(self._issue(f"UFW_DUPLICATE_{key}", "low", f"Duplicate {key} setting.", [{"action": "delete", "line_number": dup["line_number"]}], dup["line_number"]))
        for item in items[:1]:
            if item["value"].lower() not in {"yes", "no"}:
                issues.append(self._issue(
                    f"UFW_INVALID_{key}",
                    "medium",
                    f"Invalid {key} value '{item['value']}'. Expected yes or no.",
                    [{"action": "replace", "line_number": item["line_number"], "content": f"{key}={default}"}],
                    item["line_number"],
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
                    ))

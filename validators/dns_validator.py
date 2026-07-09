# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic resolv.conf validator."""

from __future__ import annotations

import ipaddress

from validators.helpers import issue


class DNSValidator:
    def __init__(self, file_path: str = "/etc/resolv.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        self._check_empty(rows, issues)
        self._check_nameservers(rows, issues)
        self._check_domain_search(rows, issues)
        self._check_runtime(data, issues)
        return issues

    def _issue(self, code: str, severity: str, desc: str, fixes: list[dict] | None = None, line: int | None = None) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line, "dns")

    def _check_empty(self, rows: list[dict], issues: list[dict]) -> None:
        if rows:
            return
        issues.append(self._issue("DNS_EMPTY_RESOLV_CONF", "high", "resolv.conf is empty."))

    def _nameservers(self, rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            if not row["is_active"]:
                continue
            parts = row["text"].split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                out.append({**row, "value": parts[1]})
        return out

    def _check_nameservers(self, rows: list[dict], issues: list[dict]) -> None:
        items = self._nameservers(rows)
        if not items:
            issues.append(self._issue("DNS_MISSING_NAMESERVER", "high", "No nameserver configured.", [{"action": "append", "content": "nameserver 1.1.1.1"}]))
            return
        seen: set[str] = set()
        valid_count = 0
        for item in items:
            value = item["value"]
            try:
                ipaddress.ip_address(value)
                valid = True
            except ValueError:
                valid = False
            if not valid:
                action = "replace" if len(items) == 1 else "delete"
                fix = {"action": action, "line_number": item["line_number"]}
                if action == "replace":
                    fix["content"] = "nameserver 1.1.1.1"
                issues.append(self._issue("DNS_INVALID_NAMESERVER", "high", f"Invalid nameserver '{value}'.", [fix], item["line_number"]))
                continue
            if value in seen:
                issues.append(self._issue("DNS_DUPLICATE_NAMESERVER", "low", f"Duplicate nameserver '{value}'.", [{"action": "delete", "line_number": item["line_number"]}], item["line_number"]))
                continue
            seen.add(value)
            valid_count += 1
            if valid_count > 3:
                issues.append(self._issue("DNS_TOO_MANY_NAMESERVERS", "low", "resolv.conf has more than three nameservers.", [{"action": "delete", "line_number": item["line_number"]}], item["line_number"]))

    def _check_domain_search(self, rows: list[dict], issues: list[dict]) -> None:
        has_domain = any(row["is_active"] and row["text"].split()[:1] == ["domain"] for row in rows)
        has_search = any(row["is_active"] and row["text"].split()[:1] == ["search"] for row in rows)
        if has_domain and has_search:
            issues.append(self._issue("DNS_DOMAIN_SEARCH_CONFLICT", "medium", "Both domain and search are set; resolver behavior depends on line order."))

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        getent = data.get("getent")
        if getent and getent["returncode"] != 0:
            issues.append(issue(
                "DNS_LOOKUP_CHECK_FAILED",
                "low",
                "A simple hostname lookup did not succeed. This may be DNS, network, or offline state.",
                self.file_path,
                [],
                None,
                "dns",
                getent.get("evidence") or "getent hosts example.com failed.",
                "No automatic repair is applied.",
                getent.get("command"),
            ))

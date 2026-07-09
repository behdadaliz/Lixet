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
        if data.get("missing_config"):
            issues.append(issue(
                "DNS_RESOLV_CONF_MISSING",
                "high",
                "resolv.conf is missing.",
                self.file_path,
                [],
                None,
                "dns",
                "The configured resolv.conf path does not exist.",
                "No automatic repair is applied because the file is missing.",
            ))
            return issues
        self._check_empty(rows, issues)
        self._check_nameservers(rows, issues, bool(data.get("managed_resolver")))
        self._check_domain_search(rows, issues)
        self._check_runtime(data, issues)
        return issues

    def _issue(
        self,
        code: str,
        severity: str,
        desc: str,
        fixes: list[dict] | None = None,
        line: int | None = None,
        safety_note: str | None = None,
        repair_level: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line, "dns", None, safety_note, None, repair_level, risk_note)

    def _check_empty(self, rows: list[dict], issues: list[dict]) -> None:
        if rows:
            return
        issues.append(self._issue(
            "DNS_EMPTY_RESOLV_CONF",
            "high",
            "resolv.conf is empty.",
            [{"action": "append", "content": "nameserver 1.1.1.1"}],
            repair_level="guarded",
            risk_note="This changes DNS resolver behavior. Review systemd-resolved management before applying.",
        ))

    def _nameservers(self, rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            if not row["is_active"]:
                continue
            parts = row["text"].split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                out.append({**row, "value": parts[1]})
        return out

    def _check_nameservers(self, rows: list[dict], issues: list[dict], managed: bool) -> None:
        items = self._nameservers(rows)
        if not items:
            fixes = [] if managed else [{"action": "append", "content": "nameserver 1.1.1.1"}]
            issues.append(self._issue(
                "DNS_MISSING_NAMESERVER",
                "high",
                "No nameserver configured.",
                fixes,
                None,
                "This appends Cloudflare DNS as a deterministic fallback and requires approval before writing.",
                "unsafe" if managed else "guarded",
                "This changes DNS resolver behavior. resolv.conf appears to be managed by systemd-resolved." if managed else "This changes DNS resolver behavior.",
            ))
            return
        seen: set[str] = set()
        valid_count = 0
        has_valid = any(self._valid_ip(item["value"]) for item in items)
        invalid_seen = 0
        for item in items:
            value = item["value"]
            valid = self._valid_ip(value)
            if not valid:
                invalid_seen += 1
                if has_valid or invalid_seen > 1:
                    fix = {"action": "comment_out_with_reason", "line_number": item["line_number"], "reason": "Lixet disabled invalid nameserver"}
                    level = "safe"
                    risk = None
                else:
                    fix = {"action": "replace_preserve_comment", "line_number": item["line_number"], "content": "nameserver 1.1.1.1"}
                    level = "guarded"
                    risk = "This changes DNS resolver behavior."
                issues.append(self._issue(
                    "DNS_INVALID_NAMESERVER",
                    "high",
                    f"Invalid nameserver '{value}'.",
                    [fix],
                    item["line_number"],
                    "Invalid nameserver lines can be replaced or removed only after approval.",
                    level,
                    risk,
                ))
                continue
            if value in seen:
                issues.append(self._issue(
                    "DNS_DUPLICATE_NAMESERVER",
                    "low",
                    f"Duplicate nameserver '{value}'.",
                    [{"action": "comment_out_with_reason", "line_number": item["line_number"], "reason": "Lixet disabled duplicate nameserver"}],
                    item["line_number"],
                    repair_level="safe",
                ))
                continue
            seen.add(value)
            valid_count += 1
            if valid_count > 3:
                issues.append(self._issue(
                    "DNS_TOO_MANY_NAMESERVERS",
                    "low",
                    "resolv.conf has more than three nameservers.",
                    [{"action": "comment_out_with_reason", "line_number": item["line_number"], "reason": "Lixet disabled extra nameserver"}],
                    item["line_number"],
                    repair_level="safe",
                ))

    @staticmethod
    def _valid_ip(value: str) -> bool:
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    def _check_domain_search(self, rows: list[dict], issues: list[dict]) -> None:
        domain = next((row for row in rows if row["is_active"] and row["text"].split()[:1] == ["domain"]), None)
        has_search = any(row["is_active"] and row["text"].split()[:1] == ["search"] for row in rows)
        if domain and has_search:
            issues.append(self._issue(
                "DNS_DOMAIN_SEARCH_CONFLICT",
                "medium",
                "Both domain and search are set; resolver behavior depends on line order.",
                [{"action": "comment_out_with_reason", "line_number": domain["line_number"], "reason": "Lixet disabled domain because search also exists"}],
                domain["line_number"],
                repair_level="guarded",
                risk_note="Changing resolver search behavior can affect hostname resolution.",
            ))

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        resolvectl = data.get("resolvectl")
        if resolvectl and resolvectl.get("timeout"):
            issues.append(issue(
                "DNS_RESOLVECTL_TIMEOUT",
                "low",
                "resolvectl status did not complete in time.",
                self.file_path,
                [],
                None,
                "dns",
                resolvectl.get("evidence") or "resolvectl status timed out.",
                "No automatic repair is applied.",
                resolvectl.get("command"),
            ))
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

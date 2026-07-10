# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Read-only resolver syntax diagnostics."""

from __future__ import annotations

import ipaddress

from validators.helpers import issue


class DNSValidator:
    def __init__(self, file_path: str = "/etc/resolv.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        if data.get("missing_config"):
            return [
                self._make(
                    "DNS_RESOLV_CONF_MISSING",
                    "high",
                    "resolv.conf is missing.",
                    evidence="The configured resolver path does not exist.",
                )
            ]
        rows = data.get("lines", [])
        manager = data.get("resolver_manager") or ("managed resolver" if data.get("managed_resolver") else None)
        if manager:
            issues.append(
                self._make(
                    "DNS_MANAGED_RESOLVER",
                    "info",
                    f"resolv.conf is managed by {manager}; Lixet will not rewrite it.",
                    evidence=self._link_evidence(data),
                )
            )
        if not any(row.get("is_active") for row in rows):
            issues.append(
                self._make("DNS_EMPTY_RESOLV_CONF", "high", "resolv.conf has no active resolver configuration.")
            )
        self._check_nameservers(rows, issues)
        self._check_search(rows, issues)
        self._check_runtime(data, issues)
        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        evidence: str | None = None,
        command: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            str(row.get("file_path")) if row else self.file_path,
            [],
            int(row["line_number"]) if row else None,
            "dns",
            evidence,
            "Resolver changes are report-only because DNS ownership and fallback policy are system-specific.",
            command,
            "unsafe",
        )

    def _check_nameservers(self, rows: list[dict], issues: list[dict]) -> None:
        nameservers: list[dict] = []
        for row in rows:
            if not row.get("is_active"):
                continue
            parts = str(row.get("text") or "").split()
            if parts[:1] == ["nameserver"]:
                nameservers.append({**row, "value": parts[1] if len(parts) > 1 else ""})
        if not nameservers:
            issues.append(
                self._make(
                    "DNS_MISSING_NAMESERVER",
                    "medium",
                    "No explicit nameserver is configured; libc may use the local machine.",
                )
            )
            return
        seen: set[str] = set()
        for index, item in enumerate(nameservers, start=1):
            value = str(item["value"])
            try:
                ipaddress.ip_address(value)
            except ValueError:
                issues.append(
                    self._make("DNS_INVALID_NAMESERVER", "high", f"Invalid nameserver address '{value}'.", item)
                )
            if value in seen:
                issues.append(self._make("DNS_DUPLICATE_NAMESERVER", "low", f"Duplicate nameserver '{value}'.", item))
            seen.add(value)
            if index > 3:
                issues.append(
                    self._make(
                        "DNS_NAMESERVER_IGNORED", "info", "glibc normally uses only the first three nameservers.", item
                    )
                )

    def _check_search(self, rows: list[dict], issues: list[dict]) -> None:
        search_rows = [
            row
            for row in rows
            if row.get("is_active") and str(row.get("text") or "").split()[:1] in (["search"], ["domain"])
        ]
        if len(search_rows) > 1:
            effective = search_rows[-1]
            evidence = "\n".join(
                f"{row.get('file_path', self.file_path)}:{row['line_number']}: {str(row.get('text'))}"
                for row in search_rows
            )
            issues.append(
                self._make(
                    "DNS_SEARCH_OVERRIDE",
                    "info",
                    "Multiple search/domain directives exist; the last one is effective.",
                    effective,
                    evidence,
                )
            )

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        result = data.get("resolvectl")
        if result and result.get("returncode") != 0:
            issues.append(
                self._make(
                    "DNS_RESOLVECTL_FAILED",
                    "low",
                    "resolvectl could not report local resolver state.",
                    evidence=result.get("evidence") or "resolvectl failed without output.",
                    command=result.get("command"),
                )
            )

    @staticmethod
    def _link_evidence(data: dict) -> str | None:
        snapshot = data.get("snapshot")
        if not snapshot or not getattr(snapshot, "is_symlink", False):
            return None
        return f"Link: {snapshot.original_path}\nTarget: {snapshot.resolved_path}"

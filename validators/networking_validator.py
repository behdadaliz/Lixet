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
        self._check_duplicate_localhost(rows, issues)
        self._check_runtime(data, issues)
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
        return issue(code, severity, desc, self.file_path, fixes, line, "networking", None, None, None, repair_level, risk_note)

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
            issues.append(self._issue("NET_MISSING_IPV4_LOCALHOST", "high", "Missing 127.0.0.1 localhost entry.", [{"action": "append", "content": "127.0.0.1 localhost"}], repair_level="safe"))
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
                repair_level="safe",
            ))

    def _check_ipv6_localhost(self, rows: list[dict], issues: list[dict]) -> None:
        items = [row for row in self._active_hosts(rows) if row["addr"] == "::1"]
        if not items:
            issues.append(self._issue("NET_MISSING_IPV6_LOCALHOST", "medium", "Missing ::1 localhost entry.", [{"action": "append", "content": "::1 localhost ip6-localhost ip6-loopback"}], repair_level="safe"))

    def _check_duplicate_localhost(self, rows: list[dict], issues: list[dict]) -> None:
        seen: set[tuple[str, str]] = set()
        for row in self._active_hosts(rows):
            names = set(row["names"])
            if "localhost" not in names:
                continue
            key = (row["addr"], "localhost")
            if key not in seen:
                seen.add(key)
                continue
            issues.append(self._issue(
                "NET_DUPLICATE_LOCALHOST",
                "low",
                f"Duplicate localhost entry for {row['addr']}.",
                [{"action": "comment_out_with_reason", "line_number": row["line_number"], "reason": "Lixet disabled duplicate localhost"}],
                row["line_number"],
                repair_level="guarded",
                risk_note="Commenting hosts entries can affect local name resolution. Review before applying.",
            ))

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        route = data.get("ip_route")
        addr = data.get("ip_addr")
        link = data.get("ip_link")
        if not route:
            issues.append(self._issue("NET_IP_COMMAND_MISSING", "info", "ip command is not available; runtime network checks were skipped."))
            return
        evidence = route.get("evidence", "")
        if route["returncode"] != 0:
            issues.append(issue("NET_ROUTE_CHECK_FAILED", "low", "Could not inspect routing table.", self.file_path, [], None, "networking", evidence, "No automatic repair is applied.", route.get("command")))
        elif not any(line.strip().startswith("default ") for line in evidence.splitlines()):
            issues.append(issue("NET_MISSING_DEFAULT_ROUTE", "high", "No default route was detected.", self.file_path, [], None, "networking", evidence or "ip route returned no default route.", "No automatic repair is applied.", route.get("command")))
        if addr and addr["returncode"] == 0:
            text = addr.get("evidence", "")
            if not self._has_non_loopback_ip(text):
                issues.append(issue("NET_NO_NON_LOOPBACK_IP", "medium", "No non-loopback IP address was detected.", self.file_path, [], None, "networking", text, "No automatic repair is applied.", addr.get("command")))
        elif addr and addr["returncode"] != 0:
            issues.append(issue("NET_ADDR_CHECK_FAILED", "low", "Could not inspect interface addresses.", self.file_path, [], None, "networking", addr.get("evidence", ""), "No automatic repair is applied.", addr.get("command")))
        if link and link["returncode"] == 0:
            if not self._has_non_loopback_up(link.get("evidence", "")):
                issues.append(issue("NET_NO_NON_LOOPBACK_LINK_UP", "medium", "No non-loopback interface appears to be up.", self.file_path, [], None, "networking", link.get("evidence", ""), "No automatic repair is applied.", link.get("command")))
        elif link and link["returncode"] != 0:
            issues.append(issue("NET_LINK_CHECK_FAILED", "low", "Could not inspect network interfaces.", self.file_path, [], None, "networking", link.get("evidence", ""), "No automatic repair is applied.", link.get("command")))

    @staticmethod
    def _has_non_loopback_ip(text: str) -> bool:
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == "inet" and not parts[1].startswith("127."):
                return True
            if len(parts) >= 2 and parts[0] == "inet6" and not parts[1].startswith("::1"):
                return True
        return False

    @staticmethod
    def _has_non_loopback_up(text: str) -> bool:
        for line in text.splitlines():
            stripped = line.strip()
            if ": " not in stripped or "<" not in stripped or ">" not in stripped:
                continue
            name = stripped.split(": ", 2)[1].split("@", 1)[0]
            flags = stripped.split("<", 1)[1].split(">", 1)[0].split(",")
            if name != "lo" and "UP" in flags:
                return True
        return False

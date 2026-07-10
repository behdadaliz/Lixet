# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Conservative hosts-file and local network diagnostics."""

from __future__ import annotations

import ipaddress

from validators.helpers import issue


class NetworkingValidator:
    def __init__(self, file_path: str = "/etc/hosts") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        hosts = self._active_hosts(rows, issues)
        self._check_localhost(rows, hosts, issues)
        self._check_duplicates(hosts, issues)
        self._check_runtime(data, issues)
        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        fixes: list[dict] | None = None,
        evidence: str | None = None,
        level: str | None = None,
        command: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            str(row.get("file_path")) if row else self.file_path,
            fixes,
            int(row["line_number"]) if row else None,
            "networking",
            evidence,
            "Localhost repairs only add the standard localhost token or missing standard line.",
            command,
            level,
        )

    def _active_hosts(self, rows: list[dict], issues: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            if not row.get("is_active"):
                continue
            body = str(row.get("raw_line") or "").split("#", 1)[0].strip()
            parts = body.split()
            if len(parts) < 2:
                issues.append(
                    self._make("HOSTS_MALFORMED_LINE", "medium", "Active hosts line has fewer than two fields.", row)
                )
                continue
            try:
                address = str(ipaddress.ip_address(parts[0]))
            except ValueError:
                issues.append(
                    self._make("HOSTS_INVALID_ADDRESS", "medium", f"Invalid hosts address '{parts[0]}'.", row)
                )
                continue
            result.append({**row, "addr": address, "names": parts[1:]})
        return result

    def _check_localhost(self, rows: list[dict], hosts: list[dict], issues: list[dict]) -> None:
        eof = str(rows[-1]["raw_line"]) if rows else ""
        ipv4 = [row for row in hosts if row["addr"] == "127.0.0.1"]
        if not ipv4:
            issues.append(
                self._make(
                    "NET_MISSING_IPV4_LOCALHOST",
                    "high",
                    "Missing 127.0.0.1 localhost entry.",
                    fixes=[{"action": "append", "content": "127.0.0.1 localhost", "expected_eof": eof}],
                    level="safe",
                )
            )
        elif "localhost" not in ipv4[0]["names"]:
            item = ipv4[0]
            issues.append(
                self._make(
                    "NET_IPV4_LOCALHOST_NAME_MISSING",
                    "high",
                    "127.0.0.1 entry does not contain localhost.",
                    item,
                    [
                        {
                            "action": "append_token",
                            "line_number": item["line_number"],
                            "token": "localhost",
                            "expected_original": item["raw_line"],
                        }
                    ],
                    level="safe",
                )
            )
        ipv6 = [row for row in hosts if row["addr"] == "::1"]
        if not ipv6:
            issues.append(
                self._make(
                    "NET_MISSING_IPV6_LOCALHOST",
                    "medium",
                    "Missing ::1 localhost entry.",
                    fixes=[
                        {"action": "append", "content": "::1 localhost ip6-localhost ip6-loopback", "expected_eof": eof}
                    ],
                    level="safe",
                )
            )

    def _check_duplicates(self, hosts: list[dict], issues: list[dict]) -> None:
        seen: set[tuple[str, str]] = set()
        for row in hosts:
            if "localhost" not in row["names"]:
                continue
            key = (row["addr"], "localhost")
            if key in seen:
                issues.append(
                    self._make(
                        "NET_DUPLICATE_LOCALHOST",
                        "low",
                        f"Another localhost alias exists for {row['addr']}; it is preserved because aliases may be intentional.",
                        row,
                    )
                )
            seen.add(key)

    def _check_runtime(self, data: dict, issues: list[dict]) -> None:
        route = data.get("ip_route")
        if not route:
            issues.append(
                self._make(
                    "NET_IP_COMMAND_UNAVAILABLE", "info", "ip is unavailable; runtime network checks were not run."
                )
            )
            return
        self._runtime_result(route, "ROUTE", "routing table", issues)
        addr = data.get("ip_addr")
        link = data.get("ip_link")
        if route.get("returncode") == 0 and not any(
            line.strip().startswith("default ") for line in str(route.get("evidence") or "").splitlines()
        ):
            issues.append(
                self._make(
                    "NET_MISSING_DEFAULT_ROUTE",
                    "high",
                    "No default route was detected.",
                    evidence=route.get("evidence"),
                    command=route.get("command"),
                )
            )
        if addr and addr.get("returncode") == 0 and not self._has_non_loopback_ip(str(addr.get("evidence") or "")):
            issues.append(
                self._make(
                    "NET_NO_NON_LOOPBACK_IP",
                    "medium",
                    "No non-loopback IP address was detected.",
                    evidence=addr.get("evidence"),
                    command=addr.get("command"),
                )
            )
        elif addr:
            self._runtime_result(addr, "ADDR", "interface addresses", issues)
        if link and link.get("returncode") == 0 and not self._has_non_loopback_up(str(link.get("evidence") or "")):
            issues.append(
                self._make(
                    "NET_NO_NON_LOOPBACK_LINK_UP",
                    "medium",
                    "No non-loopback interface appears to be up.",
                    evidence=link.get("evidence"),
                    command=link.get("command"),
                )
            )
        elif link:
            self._runtime_result(link, "LINK", "network interfaces", issues)

    def _runtime_result(self, result: dict, suffix: str, label: str, issues: list[dict]) -> None:
        if result.get("returncode") == 0:
            return
        evidence = str(result.get("evidence") or "")
        denied = "permission denied" in evidence.lower() or "operation not permitted" in evidence.lower()
        code = f"NET_{suffix}_{'PERMISSION_DENIED' if denied else 'CHECK_FAILED'}"
        description = f"Permission was denied while inspecting {label}." if denied else f"Could not inspect {label}."
        issues.append(self._make(code, "low", description, evidence=evidence, command=result.get("command")))

    @staticmethod
    def _has_non_loopback_ip(text: str) -> bool:
        return any(
            len(parts) >= 2
            and (
                (parts[0] == "inet" and not parts[1].startswith("127."))
                or (parts[0] == "inet6" and not parts[1].startswith("::1"))
            )
            for parts in (line.strip().split() for line in text.splitlines())
        )

    @staticmethod
    def _has_non_loopback_up(text: str) -> bool:
        for line in text.splitlines():
            if ": " not in line or "<" not in line or ">" not in line:
                continue
            name = line.split(": ", 2)[1].split("@", 1)[0]
            flags = line.split("<", 1)[1].split(">", 1)[0].split(",")
            if name != "lo" and "UP" in flags:
                return True
        return False

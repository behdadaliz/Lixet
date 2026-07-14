# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Conservative OpenSSH validation using first-obtained-value semantics."""

from __future__ import annotations

import ipaddress
import re

from validators.helpers import first_match, issue


class SSHValidator:
    VALID_PERMIT_ROOT_LOGIN = {"yes", "prohibit-password", "forced-commands-only", "no"}
    YES_NO = {"passwordauthentication", "pubkeyauthentication", "x11forwarding", "usepam"}
    DUPLICATE_IMPORTANT = {"port", "permitrootlogin", "passwordauthentication", "pubkeyauthentication"}

    def __init__(self, file_path: str = "/etc/ssh/sshd_config") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict | list[dict]) -> list[dict]:
        rows = data["lines"] if isinstance(data, dict) else data
        issues: list[dict] = []
        if isinstance(data, dict):
            self._check_includes(data, issues)
            self._check_config_test(data, issues)
            test = data.get("config_test")
            if test and test.get("returncode") == 0:
                return issues
            if test and test.get("returncode") != 0:
                return issues
        self._check_duplicates(rows, issues)
        self._check_port(rows, issues)
        self._check_authentication(rows, issues)
        self._check_listen_address(rows, issues)
        return issues

    @staticmethod
    def _active(rows: list[dict], directive: str, global_only: bool = False) -> list[dict]:
        return [
            item
            for item in rows
            if item.get("is_active")
            and str(item.get("directive") or "").lower() == directive.lower()
            and (not global_only or not item.get("in_match"))
        ]

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        row: dict | None = None,
        evidence: str | None = None,
        fixes: list[dict] | None = None,
        level: str = "unsafe",
        risk: str | None = None,
        source_command: str | None = None,
    ) -> dict:
        path = str(row.get("file_path")) if row else self.file_path
        line = int(row["line_number"]) if row else None
        return issue(
            code,
            severity,
            description,
            path,
            fixes,
            line,
            "ssh",
            evidence,
            "OpenSSH access settings are report-only unless sshd identifies one exact invalid line.",
            source_command,
            level,
            risk,
            "Lixet restores the protected backup if post-repair sshd validation fails." if fixes else None,
        )

    def _check_includes(self, data: dict, issues: list[dict]) -> None:
        for message in data.get("include_errors", []):
            issues.append(
                self._make("SSH_INCLUDE_ERROR", "high", "SSH include processing was incomplete.", evidence=str(message))
            )

    def _check_config_test(self, data: dict, issues: list[dict]) -> None:
        test = data.get("config_test")
        if not test:
            issues.append(
                self._make(
                    "SSH_VERIFIER_UNAVAILABLE",
                    "info",
                    "sshd is unavailable; authoritative syntax validation was not run.",
                )
            )
            return
        if test["returncode"] == 0:
            return
        evidence = test.get("evidence") or "sshd -t failed without output."
        match = first_match(r"(?P<file>(?:[A-Za-z]:)?[^:\n]+):\s*line\s*(?P<line>\d+):", evidence)
        row = self._find_row(
            data.get("lines", []), match.group("file") if match else None, int(match.group("line")) if match else None
        )
        bad = first_match(r"Bad configuration option:\s*(?P<option>\S+)", evidence)
        fixes: list[dict] = []
        level = "unsafe"
        risk = None
        if bad and row and str(row.get("directive") or "").lower() == bad.group("option").lower():
            fixes = [
                {
                    "action": "comment_out_with_reason",
                    "line_number": row["line_number"],
                    "expected_original": row["raw_line"],
                    "reason": "Lixet disabled directive rejected by sshd",
                }
            ]
            level = "guarded"
            risk = "Commenting this directive can change remote access. Keep another administrative session open."
        issues.append(
            self._make(
                "SSH_CONFIG_TEST_FAILED",
                "high",
                "sshd rejected the effective SSH configuration.",
                row=row,
                evidence=evidence,
                fixes=fixes,
                level=level,
                risk=risk,
                source_command=test.get("command"),
            )
        )

    def _check_duplicates(self, rows: list[dict], issues: list[dict]) -> None:
        for directive in sorted(self.DUPLICATE_IMPORTANT):
            items = self._active(rows, directive, global_only=True)
            for duplicate in items[1:]:
                continue

    def _check_port(self, rows: list[dict], issues: list[dict]) -> None:
        items = self._active(rows, "Port", global_only=True)
        if not items:
            return
        item = items[0]
        try:
            port = int(str(item.get("value") or ""))
        except ValueError:
            port = -1
        if not 1 <= port <= 65535:
            issues.append(
                self._make("SSH_INVALID_PORT", "high", f"Invalid SSH Port value '{item.get('value')}'.", item)
            )

    def _check_authentication(self, rows: list[dict], issues: list[dict]) -> None:
        for item in self._active(rows, "PermitRootLogin", global_only=True)[:1]:
            value = str(item.get("value") or "").lower()
            if value not in self.VALID_PERMIT_ROOT_LOGIN:
                issues.append(
                    self._make(
                        "SSH_INVALID_PERMIT_ROOT_LOGIN", "high", f"Invalid PermitRootLogin value '{value}'.", item
                    )
                )
        for name in self.YES_NO:
            for item in self._active(rows, name, global_only=True):
                value = str(item.get("value") or "").lower()
                if value not in {"yes", "no"}:
                    issues.append(
                        self._make(f"SSH_INVALID_{name.upper()}", "high", f"Invalid {name} value '{value}'.", item)
                    )

    def _check_listen_address(self, rows: list[dict], issues: list[dict]) -> None:
        for item in self._active(rows, "ListenAddress", global_only=True):
            value = str(item.get("value") or "").split()[0] if item.get("value") else ""
            if not value or not self._valid_listen(value):
                issues.append(
                    self._make(
                        "SSH_INVALID_LISTEN_ADDRESS",
                        "high",
                        f"ListenAddress '{value}' is not a valid address, hostname, or optional port form.",
                        item,
                    )
                )

    @staticmethod
    def _valid_listen(value: str) -> bool:
        host = value
        port: str | None = None
        if value.startswith("["):
            close = value.find("]")
            if close < 0:
                return False
            host = value[1:close]
            rest = value[close + 1 :]
            if rest:
                if not rest.startswith(":"):
                    return False
                port = rest[1:]
        elif value.count(":") == 1:
            left, right = value.rsplit(":", 1)
            if right.isdigit():
                host, port = left, right
        if port is not None:
            try:
                if not 1 <= int(port) <= 65535:
                    return False
            except ValueError:
                return False
        if host == "*":
            return True
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return bool(re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host))

    @staticmethod
    def _find_row(rows: list[dict], file_path: str | None, line: int | None) -> dict | None:
        if line is None:
            return None
        for row in rows:
            if int(row.get("line_number") or 0) != line:
                continue
            if file_path is None or str(row.get("file_path")) == file_path:
                return row
        return None

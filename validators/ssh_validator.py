# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic SSH configuration validator."""

from __future__ import annotations

import ipaddress

from validators.helpers import first_match, issue


class SSHValidator:
    """Validate a parsed sshd_config and emit deterministic fixes."""

    VALID_PERMIT_ROOT_LOGIN = {"yes", "prohibit-password", "forced-commands-only", "no"}
    YES_NO = {"PasswordAuthentication", "PubkeyAuthentication", "X11Forwarding", "UsePAM"}

    def __init__(self, file_path: str = "/etc/ssh/sshd_config") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict | list[dict]) -> list[dict]:
        parsed_data = data["lines"] if isinstance(data, dict) else data
        issues: list[dict] = []
        if isinstance(data, dict):
            self._check_config_test(data, issues)
        self._check_missing_port(parsed_data, issues)
        self._check_duplicate_ports(parsed_data, issues)
        self._check_invalid_ports(parsed_data, issues)
        self._check_permit_root_login(parsed_data, issues)
        self._check_yes_no(parsed_data, issues)
        self._check_listen_address(parsed_data, issues)
        return issues

    def _active(self, parsed_data: list[dict], directive: str, global_only: bool = False) -> list[dict]:
        return [
            item for item in parsed_data
            if item["is_active"] and item["directive"] and item["directive"].lower() == directive.lower()
            and (not global_only or not item.get("in_match"))
        ]

    def _issue(
        self,
        code: str,
        severity: str,
        description: str,
        fixes: list[dict] | None = None,
        line_number: int | None = None,
        evidence: str | None = None,
    ) -> dict:
        return issue(code, severity, description, self.file_path, fixes, line_number, "ssh", evidence)

    def _check_config_test(self, data: dict, issues: list[dict]) -> None:
        test = data.get("config_test")
        if not test or test["returncode"] == 0:
            return
        evidence = test.get("evidence") or "sshd -t failed without output."
        line_number = None
        file_path = self.file_path
        match = first_match(r"(?P<file>[^:\n]+):\s*line\s*(?P<line>\d+):", evidence)
        if match:
            file_path = match.group("file")
            line_number = int(match.group("line"))
        issues.append(issue(
            "SSH_CONFIG_TEST_FAILED",
            "high",
            "SSH configuration test failed.",
            file_path,
            [],
            line_number,
            "ssh",
            evidence,
        ))

    def _check_missing_port(self, parsed_data: list[dict], issues: list[dict]) -> None:
        if self._active(parsed_data, "Port", global_only=True):
            return
        first_match = next((item for item in parsed_data if item["is_active"] and str(item["directive"]).lower() == "match"), None)
        fix = {"action": "append", "content": "Port 22"}
        if first_match:
            fix = {"action": "insert_before", "line_number": first_match["line_number"], "content": "Port 22"}
        issues.append(self._issue(
            "SSH_MISSING_PORT",
            "low",
            "No explicit Port directive found; SSH will use the default port 22.",
            [fix],
        ))

    def _check_duplicate_ports(self, parsed_data: list[dict], issues: list[dict]) -> None:
        port_lines = self._active(parsed_data, "Port", global_only=True)
        for duplicate in port_lines[1:]:
            issues.append(self._issue(
                "SSH_DUPLICATE_PORT",
                "medium",
                f"Duplicate Port directive found with value '{duplicate['value']}'.",
                [{"action": "delete", "line_number": duplicate["line_number"]}],
                duplicate["line_number"],
            ))

    def _check_invalid_ports(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for port in self._active(parsed_data, "Port", global_only=True)[:1]:
            try:
                port_num = int(str(port["value"]))
            except ValueError:
                port_num = -1
            if not 1 <= port_num <= 65535:
                issues.append(self._issue(
                    "SSH_INVALID_PORT",
                    "high",
                    f"Invalid Port value '{port['value']}'. Must be an integer between 1 and 65535.",
                    [{"action": "replace", "line_number": port["line_number"], "content": "Port 22"}],
                    port["line_number"],
                ))

    def _check_permit_root_login(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for item in self._active(parsed_data, "PermitRootLogin"):
            value = str(item["value"]).lower()
            if value not in self.VALID_PERMIT_ROOT_LOGIN:
                issues.append(self._issue(
                    "SSH_INVALID_PERMIT_ROOT_LOGIN",
                    "high",
                    f"Invalid PermitRootLogin value '{item['value']}'.",
                    [{"action": "replace", "line_number": item["line_number"], "content": "PermitRootLogin prohibit-password"}],
                    item["line_number"],
                ))

    def _check_yes_no(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for name in self.YES_NO:
            for item in self._active(parsed_data, name):
                value = str(item["value"]).lower()
                if value not in {"yes", "no"}:
                    issues.append(self._issue(
                        f"SSH_INVALID_{name.upper()}",
                        "medium",
                        f"Invalid {name} value '{item['value']}'. Expected yes or no.",
                        [{"action": "replace", "line_number": item["line_number"], "content": f"{name} no"}],
                        item["line_number"],
                    ))

    def _check_listen_address(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for item in self._active(parsed_data, "ListenAddress", global_only=True):
            value = str(item["value"]).split()[0]
            if not value:
                issues.append(self._issue("SSH_EMPTY_LISTEN_ADDRESS", "medium", "ListenAddress has no value.", [], item["line_number"]))
                continue
            try:
                ipaddress.ip_address(value)
            except ValueError:
                issues.append(self._issue(
                    "SSH_INVALID_LISTEN_ADDRESS",
                    "medium",
                    f"ListenAddress '{value}' is not a valid IP address.",
                    [],
                    item["line_number"],
                ))

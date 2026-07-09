# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic SSH configuration validator."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from validators.helpers import first_match, issue


class SSHValidator:
    """Validate a parsed sshd_config and emit deterministic fixes."""

    VALID_PERMIT_ROOT_LOGIN = {"yes", "prohibit-password", "forced-commands-only", "no"}
    YES_NO = {"PasswordAuthentication", "PubkeyAuthentication", "X11Forwarding", "UsePAM"}
    YES_NO_DEFAULTS = {
        "PasswordAuthentication": "no",
        "PubkeyAuthentication": "yes",
        "X11Forwarding": "no",
        "UsePAM": "yes",
    }
    DUPLICATE_IMPORTANT = {"PermitRootLogin", "PasswordAuthentication", "PubkeyAuthentication"}

    def __init__(self, file_path: str = "/etc/ssh/sshd_config") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict | list[dict]) -> list[dict]:
        parsed_data = data["lines"] if isinstance(data, dict) else data
        issues: list[dict] = []
        if isinstance(data, dict):
            self._check_config_test(data, issues)
        self._check_empty_config(parsed_data, issues)
        self._check_missing_port(parsed_data, issues)
        self._check_duplicate_ports(parsed_data, issues)
        self._check_duplicate_important(parsed_data, issues)
        self._check_invalid_ports(parsed_data, issues)
        self._check_permit_root_login(parsed_data, issues)
        self._check_risky_values(parsed_data, issues)
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
        repair_level: str | None = None,
        safety_note: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        return issue(code, severity, description, self.file_path, fixes, line_number, "ssh", evidence, safety_note, None, repair_level, risk_note)

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
        fixes: list[dict] = []
        repair_level = "unsafe"
        risk_note = None
        bad = first_match(r"Bad configuration option:\s*(?P<option>\S+)", evidence)
        if bad and line_number and self._line_has_directive(file_path, line_number, bad.group("option")):
            fixes = [{
                "action": "comment_out_with_reason",
                "line_number": line_number,
                "reason": "Lixet disabled invalid directive",
            }]
            repair_level = "guarded"
            risk_note = "This comments out a directive rejected by sshd. Review the line before applying."
        item = issue(
            "SSH_CONFIG_TEST_FAILED",
            "high",
            "SSH configuration test failed.",
            file_path,
            fixes,
            line_number,
            "ssh",
            evidence,
            "No safe automatic repair available." if not fixes else "A guarded repair can comment out the exact invalid directive.",
            test.get("command"),
            repair_level,
            risk_note,
            "A backup is restored automatically if sshd verification fails.",
        )
        if bad:
            item["bad_option"] = bad.group("option")
        issues.append(item)

    def _check_empty_config(self, parsed_data: list[dict], issues: list[dict]) -> None:
        if parsed_data:
            return
        issues.append(self._issue("SSH_EMPTY_CONFIG", "high", "SSH configuration file is empty.", [], None))

    def _check_missing_port(self, parsed_data: list[dict], issues: list[dict]) -> None:
        if self._active(parsed_data, "Port", global_only=True):
            return
        first_match_block = next((item for item in parsed_data if item["is_active"] and str(item["directive"]).lower() == "match"), None)
        fix = {"action": "append", "content": "Port 22"}
        if first_match_block:
            fix = {"action": "insert_before", "line_number": first_match_block["line_number"], "content": "Port 22"}
        issues.append(self._issue(
            "SSH_MISSING_PORT",
            "info",
            "No explicit Port directive found; SSH will use the default port 22.",
            [fix],
            repair_level="safe",
            safety_note="This only makes the existing default SSH port explicit.",
        ))

    def _check_duplicate_ports(self, parsed_data: list[dict], issues: list[dict]) -> None:
        port_lines = self._active(parsed_data, "Port", global_only=True)
        for duplicate in port_lines[1:]:
            issues.append(self._issue(
                "SSH_DUPLICATE_PORT",
                "medium",
                f"Duplicate Port directive found with value '{duplicate['value']}'. OpenSSH normally uses the first active value.",
                [{"action": "comment_out_with_reason", "line_number": duplicate["line_number"], "reason": "Lixet disabled duplicate"}],
                duplicate["line_number"],
                repair_level="guarded",
                risk_note="Changing active Port directives can affect SSH access. Confirm another access path first.",
            ))

    def _check_duplicate_important(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for name in self.DUPLICATE_IMPORTANT:
            items = self._active(parsed_data, name, global_only=True)
            for duplicate in items[1:]:
                issues.append(self._issue(
                    f"SSH_DUPLICATE_{name.upper()}",
                    "medium",
                    f"Duplicate {name} directive found. OpenSSH normally uses the first active value.",
                    [],
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
                    repair_level="guarded",
                    risk_note="Changing the SSH port can affect remote access. Make sure port 22 is reachable before applying.",
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
                    repair_level="guarded",
                    risk_note="This changes root login behavior. Make sure you have another working login method.",
                ))

    def _check_risky_values(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for item in self._active(parsed_data, "PermitRootLogin", global_only=True)[:1]:
            if str(item["value"]).lower() == "yes":
                issues.append(self._issue(
                    "SSH_ROOT_LOGIN_ENABLED",
                    "medium",
                    "PermitRootLogin is enabled. This can increase SSH exposure on public servers.",
                    [{"action": "replace", "line_number": item["line_number"], "content": "PermitRootLogin prohibit-password"}],
                    item["line_number"],
                    repair_level="guarded",
                    risk_note="This may change how root logs in. Make sure you have another working login method.",
                ))
        for item in self._active(parsed_data, "PasswordAuthentication", global_only=True)[:1]:
            if str(item["value"]).lower() == "yes":
                issues.append(self._issue(
                    "SSH_PASSWORD_AUTH_ENABLED",
                    "medium",
                    "PasswordAuthentication is enabled. Review this if the server is reachable from the internet.",
                    [{"action": "replace", "line_number": item["line_number"], "content": "PasswordAuthentication no"}],
                    item["line_number"],
                    repair_level="guarded",
                    risk_note="This may block password login. Make sure SSH key login works first.",
                ))

    def _check_yes_no(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for name in self.YES_NO:
            for item in self._active(parsed_data, name):
                value = str(item["value"]).lower()
                if value not in {"yes", "no"}:
                    default = self.YES_NO_DEFAULTS[name]
                    severity = "high" if name == "PasswordAuthentication" else "medium"
                    issues.append(self._issue(
                        f"SSH_INVALID_{name.upper()}",
                        severity,
                        f"Invalid {name} value '{item['value']}'. Expected yes or no.",
                        [{"action": "replace", "line_number": item["line_number"], "content": f"{name} {default}"}],
                        item["line_number"],
                        repair_level="guarded",
                        risk_note="Changing SSH authentication directives can affect access. Review before applying.",
                    ))

    def _check_listen_address(self, parsed_data: list[dict], issues: list[dict]) -> None:
        for item in self._active(parsed_data, "ListenAddress", global_only=True):
            value = str(item["value"]).split()[0]
            if not value:
                issues.append(self._issue(
                    "SSH_EMPTY_LISTEN_ADDRESS",
                    "medium",
                    "ListenAddress has no value.",
                    [{"action": "comment_out_with_reason", "line_number": item["line_number"], "reason": "Lixet disabled empty ListenAddress"}],
                    item["line_number"],
                    repair_level="safe",
                    safety_note="The empty ListenAddress line is not useful and can be commented out.",
                ))
                continue
            try:
                ipaddress.ip_address(value)
            except ValueError:
                issues.append(self._issue(
                    "SSH_INVALID_LISTEN_ADDRESS",
                    "medium",
                    f"ListenAddress '{value}' is not a valid IP address.",
                    [{"action": "comment_out_with_reason", "line_number": item["line_number"], "reason": "Lixet disabled invalid ListenAddress"}],
                    item["line_number"],
                    repair_level="guarded",
                    risk_note="Changing ListenAddress can affect which addresses SSH listens on.",
                ))

    @staticmethod
    def _line_has_directive(file_path: str, line_number: int, directive: str) -> bool:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return False
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return False
        if line_number < 1 or line_number > len(lines):
            return False
        return lines[line_number - 1].strip().split(None, 1)[:1] == [directive]

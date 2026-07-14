# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Conservative Nginx diagnostics backed by nginx -t when available."""

from __future__ import annotations

import re
from pathlib import Path

from validators.helpers import first_match, issue


class NginxValidator:
    SIMPLE = {
        "access_log",
        "client_max_body_size",
        "error_log",
        "gzip",
        "include",
        "index",
        "keepalive_timeout",
        "listen",
        "pid",
        "proxy_pass",
        "return",
        "root",
        "sendfile",
        "server_name",
        "try_files",
        "types_hash_max_size",
        "user",
        "worker_connections",
        "worker_processes",
    }

    def __init__(self, file_path: str = "/etc/nginx/nginx.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        self._check_includes(data, issues)
        self._check_config_test(data, issues)
        test = data.get("config_test")
        if test and test.get("returncode") == 0:
            return issues
        if test and test.get("returncode") != 0:
            return issues
        self._check_braces(rows, issues)
        self._check_semicolons(rows, issues)
        self._check_worker_processes(rows, issues)
        self._check_events_block(rows, issues)
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
            "nginx",
            evidence,
            "Handwritten parser findings are report-only; use nginx -t as the authoritative verifier.",
            command,
            "unsafe",
        )

    def _check_includes(self, data: dict, issues: list[dict]) -> None:
        for message in data.get("include_errors", []):
            issues.append(
                self._make(
                    "NGINX_INCLUDE_ERROR", "high", "Nginx include processing was incomplete.", evidence=str(message)
                )
            )

    def _check_config_test(self, data: dict, issues: list[dict]) -> None:
        test = data.get("config_test")
        if not test:
            issues.append(
                self._make(
                    "NGINX_VERIFIER_UNAVAILABLE",
                    "info",
                    "nginx is unavailable; authoritative syntax validation was not run.",
                )
            )
            return
        if test["returncode"] == 0:
            return
        evidence = test.get("evidence") or "nginx -t failed without output."
        match = first_match(r"in\s+(?P<file>\S+):(?P<line>\d+)", evidence)
        row = self._find_row(
            data.get("lines", []), match.group("file") if match else None, int(match.group("line")) if match else None
        )
        issues.append(
            self._make(
                "NGINX_CONFIG_TEST_FAILED",
                "high",
                "nginx rejected the effective configuration.",
                row,
                evidence,
                test.get("command"),
            )
        )

    def _check_braces(self, rows: list[dict], issues: list[dict]) -> None:
        stacks: dict[str, list[dict]] = {}
        for row in rows:
            path = str(row.get("file_path") or self.file_path)
            stack = stacks.setdefault(path, [])
            code = self._code(str(row.get("raw_line") or ""))
            for char in code:
                if char == "{":
                    stack.append(row)
                elif char == "}":
                    if stack:
                        stack.pop()
                    else:
                        issues.append(
                            self._make("NGINX_UNMATCHED_CLOSE_BRACE", "high", "Unmatched closing brace.", row)
                        )
        for stack in stacks.values():
            for row in stack:
                issues.append(
                    self._make("NGINX_UNCLOSED_BLOCK", "high", "Nginx block is not closed in this file.", row)
                )

    def _check_semicolons(self, rows: list[dict], issues: list[dict]) -> None:
        for row in rows:
            if not row.get("is_active"):
                continue
            code = self._code(str(row.get("raw_line") or "")).strip()
            if not code or code.endswith((";", "{", "}")) or "{" in code or "}" in code:
                continue
            key = code.split(None, 1)[0]
            if key in self.SIMPLE:
                issues.append(
                    self._make(
                        "NGINX_MISSING_SEMICOLON", "medium", f"Directive '{key}' may be missing a semicolon.", row
                    )
                )

    def _check_worker_processes(self, rows: list[dict], issues: list[dict]) -> None:
        for row in rows:
            code = self._code(str(row.get("raw_line") or "")).strip()
            match = re.fullmatch(r"worker_processes\s+([^;]+);", code)
            if not match:
                continue
            value = match.group(1).strip()
            if value == "auto":
                continue
            try:
                valid = int(value) > 0
            except ValueError:
                valid = False
            if not valid:
                issues.append(
                    self._make(
                        "NGINX_INVALID_WORKER_PROCESSES", "medium", f"Invalid worker_processes value '{value}'.", row
                    )
                )

    def _check_events_block(self, rows: list[dict], issues: list[dict]) -> None:
        if Path(self.file_path).name != "nginx.conf":
            return
        root_rows = [
            row
            for row in rows
            if Path(str(row.get("file_path") or self.file_path)).absolute() == Path(self.file_path).absolute()
        ]
        if any(re.search(r"(^|[;}])\s*events\s*\{", self._code(str(row.get("raw_line") or ""))) for row in root_rows):
            return
        issues.append(self._make("NGINX_MISSING_EVENTS", "high", "The main configuration has no events block."))

    @staticmethod
    def _code(text: str) -> str:
        quote: str | None = None
        escaped = False
        output: list[str] = []
        for char in text:
            if escaped:
                output.append(" ")
                escaped = False
                continue
            if char == "\\":
                output.append(" ")
                escaped = True
                continue
            if quote:
                output.append(" ")
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
                output.append(" ")
                continue
            if char == "#":
                break
            output.append(char)
        return "".join(output)

    @staticmethod
    def _find_row(rows: list[dict], file_path: str | None, line: int | None) -> dict | None:
        if line is None:
            return None
        for row in rows:
            if int(row.get("line_number") or 0) == line and (
                file_path is None or str(row.get("file_path")) == file_path
            ):
                return row
        return None

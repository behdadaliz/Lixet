# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic Nginx configuration validator."""

from __future__ import annotations

from pathlib import Path

from validators.helpers import issue


class NginxValidator:
    SIMPLE = {
        "access_log", "client_max_body_size", "error_log", "gzip", "include", "index",
        "keepalive_timeout", "listen", "pid", "proxy_pass", "return", "root",
        "sendfile", "server_name", "try_files", "types_hash_max_size", "user",
        "worker_connections", "worker_processes",
    }

    def __init__(self, file_path: str = "/etc/nginx/nginx.conf") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        self._check_braces(rows, issues)
        self._check_semicolons(rows, issues)
        self._check_worker_processes(rows, issues)
        self._check_events_block(rows, issues)
        return issues

    def _issue(self, code: str, severity: str, desc: str, fixes: list[dict] | None = None, line: int | None = None) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line)

    def _clean(self, row: dict) -> str:
        txt = row["text"]
        return txt.split("#", 1)[0].strip()

    def _check_braces(self, rows: list[dict], issues: list[dict]) -> None:
        stack: list[int] = []
        for row in rows:
            txt = self._clean(row)
            for char in txt:
                if char == "{":
                    stack.append(row["line_number"])
                elif char == "}":
                    if not stack:
                        issues.append(self._issue("NGINX_UNMATCHED_CLOSE_BRACE", "high", "Unmatched closing brace.", [], row["line_number"]))
                    else:
                        stack.pop()
        for line in stack:
            issues.append(self._issue("NGINX_UNCLOSED_BLOCK", "high", "Nginx block is not closed.", [], line))

    def _check_semicolons(self, rows: list[dict], issues: list[dict]) -> None:
        for row in rows:
            if not row["is_active"]:
                continue
            txt = self._clean(row)
            if not txt or txt.endswith((";", "{", "}")):
                continue
            key = txt.split(None, 1)[0]
            if key not in self.SIMPLE:
                issues.append(self._issue("NGINX_MISSING_SEMICOLON", "medium", f"Directive '{key}' may be missing a semicolon.", [], row["line_number"]))
                continue
            issues.append(self._issue(
                "NGINX_MISSING_SEMICOLON",
                "medium",
                f"Directive '{key}' is missing a semicolon.",
                [{"action": "replace", "line_number": row["line_number"], "content": self._semicolon(row["raw_line"])}],
                row["line_number"],
            ))

    def _check_worker_processes(self, rows: list[dict], issues: list[dict]) -> None:
        for row in rows:
            txt = self._clean(row)
            if not txt.startswith("worker_processes "):
                continue
            if not txt.endswith(";"):
                continue
            value = txt.rstrip(";").split(None, 1)[1].strip()
            if value == "auto":
                continue
            try:
                ok = int(value) > 0
            except ValueError:
                ok = False
            if not ok:
                issues.append(self._issue(
                    "NGINX_INVALID_WORKER_PROCESSES",
                    "medium",
                    f"Invalid worker_processes value '{value}'.",
                    [{"action": "replace", "line_number": row["line_number"], "content": "worker_processes auto;"}],
                    row["line_number"],
                ))

    def _check_events_block(self, rows: list[dict], issues: list[dict]) -> None:
        if Path(self.file_path).name != "nginx.conf":
            return
        if any(self._clean(row).startswith("events") and self._clean(row).endswith("{") for row in rows):
            return
        issues.append(self._issue(
            "NGINX_MISSING_EVENTS",
            "high",
            "Missing events block.",
            [{"action": "append", "content": "events {\n    worker_connections 1024;\n}"}],
        ))

    @staticmethod
    def _semicolon(raw: str) -> str:
        body = raw.rstrip("\r\n")
        if "#" not in body:
            return body.rstrip() + ";"
        left, right = body.split("#", 1)
        return f"{left.rstrip()}; #{right.strip()}"

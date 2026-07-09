# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic Nginx configuration validator."""

from __future__ import annotations

from pathlib import Path

from validators.helpers import first_match, issue


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
        self._check_config_test(data, issues)
        self._check_empty_config(rows, issues)
        self._check_braces(rows, issues)
        self._check_semicolons(rows, issues)
        self._check_worker_processes(rows, issues)
        self._check_events_block(rows, issues)
        return issues

    def _issue(
        self,
        code: str,
        severity: str,
        desc: str,
        fixes: list[dict] | None = None,
        line: int | None = None,
        repair_level: str | None = None,
        safety_note: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        return issue(code, severity, desc, self.file_path, fixes, line, "nginx", None, safety_note, None, repair_level, risk_note)

    def _check_config_test(self, data: dict, issues: list[dict]) -> None:
        test = data.get("config_test")
        if not test or test["returncode"] == 0:
            return
        evidence = test.get("evidence") or "nginx -t failed without output."
        file_path = self.file_path
        line_number = None
        match = first_match(r"in\s+(?P<file>\S+):(?P<line>\d+)", evidence)
        if match:
            file_path = match.group("file")
            line_number = int(match.group("line"))
        fixes: list[dict] = []
        repair_level = "unsafe"
        risk_note = None
        directive = first_match(r"unknown directive\s+\"?(?P<directive>[A-Za-z0-9_:-]+)\"?", evidence)
        if directive and line_number and self._line_has_text(file_path, line_number, directive.group("directive")):
            fixes = [{
                "action": "comment_out_with_reason",
                "line_number": line_number,
                "reason": "Lixet disabled invalid directive",
            }]
            repair_level = "guarded"
            risk_note = "This comments out a directive rejected by nginx. Review the line before applying."
        item = issue(
            "NGINX_CONFIG_TEST_FAILED",
            "high",
            "Nginx configuration test failed.",
            file_path,
            fixes,
            line_number,
            "nginx",
            evidence,
            "No safe automatic repair available." if not fixes else "A guarded repair can comment out the exact invalid directive.",
            test.get("command"),
            repair_level,
            risk_note,
            "A backup is restored automatically if nginx verification fails.",
        )
        if directive:
            item["directive"] = directive.group("directive")
        issues.append(item)

    def _check_empty_config(self, rows: list[dict], issues: list[dict]) -> None:
        if rows:
            return
        issues.append(self._issue("NGINX_EMPTY_CONFIG", "high", "Nginx configuration file is empty."))

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
                        issues.append(self._issue("NGINX_UNMATCHED_CLOSE_BRACE", "high", "Unmatched closing brace.", [], row["line_number"], repair_level="unsafe"))
                    else:
                        stack.pop()
        if len(stack) == 1:
            issues.append(self._issue(
                "NGINX_UNCLOSED_BLOCK",
                "high",
                "Nginx block is not closed.",
                [{"action": "append", "content": "}"}],
                stack[0],
                repair_level="guarded",
                risk_note="This appends one closing brace. Nginx syntax verification must pass after repair.",
            ))
            return
        for line in stack:
            issues.append(self._issue("NGINX_UNCLOSED_BLOCK", "high", "Nginx block is not closed.", [], line, repair_level="unsafe"))

    def _check_semicolons(self, rows: list[dict], issues: list[dict]) -> None:
        for row in rows:
            if not row["is_active"]:
                continue
            txt = self._clean(row)
            if not txt or txt.endswith((";", "{", "}")):
                continue
            key = txt.split(None, 1)[0]
            if key not in self.SIMPLE:
                issues.append(self._issue("NGINX_MISSING_SEMICOLON", "medium", f"Directive '{key}' may be missing a semicolon.", [], row["line_number"], repair_level="unsafe"))
                continue
            issues.append(self._issue(
                "NGINX_MISSING_SEMICOLON",
                "medium",
                f"Directive '{key}' is missing a semicolon.",
                [{"action": "replace", "line_number": row["line_number"], "content": self._semicolon(row["raw_line"])}],
                row["line_number"],
                repair_level="safe",
                safety_note="This adds a missing semicolon to a known simple directive.",
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
                    repair_level="safe",
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
            repair_level="guarded",
            risk_note="This changes the main nginx.conf structure and must pass nginx syntax verification.",
        ))

    @staticmethod
    def _semicolon(raw: str) -> str:
        body = raw.rstrip("\r\n")
        if "#" not in body:
            return body.rstrip() + ";"
        left, right = body.split("#", 1)
        return f"{left.rstrip()}; # {right.strip()}"

    @staticmethod
    def _line_has_text(file_path: str, line_number: int, needle: str) -> bool:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return False
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return False
        if line_number < 1 or line_number > len(lines):
            return False
        return needle in lines[line_number - 1]

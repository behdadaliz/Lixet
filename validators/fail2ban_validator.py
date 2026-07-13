# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Conservative Fail2ban diagnostics."""

from __future__ import annotations

import re
from pathlib import Path

from validators.helpers import issue


class Fail2banValidator:
    BOOL_KEYS = {"enabled", "ignoreself"}
    BOOL_VALUES = {"true", "false", "yes", "no", "on", "off", "1", "0"}
    POSITIVE_INT_KEYS = {"maxretry", "maxmatches"}
    SPECIAL_SECTIONS = {"default", "includes"}
    LOCATION_RE = re.compile(r"(?P<file>/[^\s:]+):(?P<line>\d+)")

    def __init__(self, file_path: str = "/etc/fail2ban") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        issues: list[dict] = []
        self._include_errors(data, issues)
        self._authoritative_test(data, issues)
        sections = self._parse_files(data, issues)
        self._enabled_filters(data, sections, issues)
        self._runtime(data.get("runtime_status"), issues)
        return issues

    def _make(
        self,
        code: str,
        severity: str,
        description: str,
        path: str | None = None,
        row: dict | None = None,
        evidence: str | None = None,
        command: str | None = None,
        fixes: list[dict] | None = None,
        level: str = "unsafe",
        risk: str | None = None,
    ) -> dict:
        return issue(
            code,
            severity,
            description,
            path or (str(row.get("file_path")) if row else self.file_path),
            fixes,
            int(row["line_number"]) if row else None,
            "fail2ban",
            evidence,
            "Fail2ban findings are report-only unless an exact guarded override-line repair is proven.",
            command,
            level,
            risk,
            "A protected backup is restored if fail2ban-client validation fails." if fixes else None,
        )

    def _include_errors(self, data: dict, issues: list[dict]) -> None:
        for message in data.get("include_errors") or []:
            text = str(message)
            code = "FAIL2BAN_INCLUDE_ERROR"
            if "cycle" in text.lower():
                code = "FAIL2BAN_INCLUDE_CYCLE"
            elif "missing" in text.lower():
                code = "FAIL2BAN_INCLUDE_MISSING"
            elif "cannot read" in text.lower() or "cannot resolve" in text.lower():
                code = "FAIL2BAN_INCLUDE_UNREADABLE"
            issues.append(self._make(code, "medium", "Fail2ban include processing reported a problem.", evidence=text))

    def _authoritative_test(self, data: dict, issues: list[dict]) -> None:
        result = data.get("config_test")
        if result is None:
            issues.append(
                self._make(
                    "FAIL2BAN_VERIFIER_UNAVAILABLE",
                    "info",
                    "fail2ban-client is unavailable; authoritative Fail2ban validation was not run.",
                )
            )
            return
        if result.get("returncode") == 0:
            return
        evidence = str(result.get("evidence") or "fail2ban-client -t failed without output.")
        path, line = self._location(evidence)
        row = self._find_row(data.get("files", []), path, line)
        fixes: list[dict] = []
        level = "unsafe"
        risk = None
        if row and self._user_override(path):
            fixes = [
                {
                    "action": "comment_out_with_reason",
                    "line_number": row["line_number"],
                    "expected_original": row["raw_line"],
                    "reason": "Lixet disabled line rejected by fail2ban-client",
                }
            ]
            level = "guarded"
            risk = "This disables one Fail2ban override line. Review the jail policy before approval."
        issues.append(
            self._make(
                "FAIL2BAN_CONFIG_TEST_FAILED",
                "high",
                "fail2ban-client rejected the configuration.",
                path,
                row,
                evidence,
                result.get("command"),
                fixes,
                level,
                risk,
            )
        )

    def _parse_files(self, data: dict, issues: list[dict]) -> dict[str, dict[str, dict]]:
        sections: dict[str, dict[str, dict]] = {}
        seen_sections: set[tuple[str, str]] = set()
        for file_data in data.get("files", []):
            current: str | None = None
            file_path = str(file_data.get("file_path") or self.file_path)
            for row in file_data.get("lines", []):
                text = str(row.get("text") or "")
                if not row.get("is_active"):
                    continue
                if text.startswith("["):
                    if not re.fullmatch(r"\[[^\[\]\s][^\[\]]*\]", text):
                        issues.append(self._make("FAIL2BAN_MALFORMED_SECTION", "medium", "Malformed section header.", file_path, row, text))
                        current = None
                        continue
                    current = text[1:-1].strip()
                    key = (file_path, current.lower())
                    if key in seen_sections:
                        issues.append(self._make("FAIL2BAN_DUPLICATE_SECTION", "info", f"Section [{current}] appears more than once in one file; later values may override earlier ones.", file_path, row))
                    seen_sections.add(key)
                    sections.setdefault(current.lower(), {"name": current, "options": {}, "path": file_path})
                    continue
                if "=" not in text or current is None:
                    continue
                name, value = text.split("=", 1)
                option = name.strip().lower()
                if not option:
                    issues.append(self._make("FAIL2BAN_EMPTY_OPTION", "medium", "Fail2ban option name is empty.", file_path, row, text))
                    continue
                clean_value = value.strip()
                section = sections.setdefault(current.lower(), {"name": current, "options": {}, "path": file_path})
                options = section["options"]
                if option in options:
                    issues.append(self._make("FAIL2BAN_DUPLICATE_OPTION", "info", f"Option '{option}' appears more than once in section [{current}]; the last value is effective.", file_path, row))
                options[option] = {"value": clean_value, "row": row, "path": file_path}
                self._validate_value(option, clean_value, file_path, row, issues)
        return sections

    def _validate_value(self, option: str, value: str, path: str, row: dict, issues: list[dict]) -> None:
        if "%(" in value:
            return
        if option in self.BOOL_KEYS and value.lower() not in self.BOOL_VALUES:
            issues.append(self._make("FAIL2BAN_INVALID_BOOLEAN", "medium", f"Option '{option}' has an invalid boolean value.", path, row, value))
        if option in self.POSITIVE_INT_KEYS:
            try:
                valid = int(value) > 0
            except ValueError:
                valid = False
            if not valid:
                issues.append(self._make("FAIL2BAN_INVALID_POSITIVE_INTEGER", "medium", f"Option '{option}' must be a positive integer.", path, row, value))

    def _enabled_filters(self, data: dict, sections: dict[str, dict], issues: list[dict]) -> None:
        config_dir = Path(str(data.get("config_dir") or self.file_path))
        for key, section in sections.items():
            if key in self.SPECIAL_SECTIONS:
                continue
            options = section.get("options", {})
            enabled = options.get("enabled")
            if not enabled or str(enabled["value"]).lower() not in {"true", "yes", "on", "1"}:
                continue
            filter_value = str(options.get("filter", {}).get("value") or section["name"])
            filter_name = filter_value.split("[", 1)[0].strip()
            if "%(" in filter_name or not filter_name:
                continue
            if not self._filter_exists(config_dir, filter_name):
                row = enabled["row"]
                issues.append(
                    self._make(
                        "FAIL2BAN_ENABLED_JAIL_MISSING_FILTER",
                        "medium",
                        f"Enabled jail [{section['name']}] references missing filter '{filter_name}'.",
                        str(enabled["path"]),
                        row,
                    )
                )

    def _runtime(self, result: dict | None, issues: list[dict]) -> None:
        if result is None:
            issues.append(self._make("FAIL2BAN_COMMAND_UNAVAILABLE", "info", "fail2ban-client status is unavailable."))
            return
        evidence = str(result.get("evidence") or "")
        if result.get("returncode") != 0:
            issues.append(
                self._make(
                    "FAIL2BAN_STATUS_FAILED",
                    "low",
                    "Could not read Fail2ban runtime status.",
                    evidence=evidence,
                    command=result.get("command"),
                )
            )
        elif "jail list:" in evidence.lower() and not evidence.split("Jail list:", 1)[-1].strip():
            issues.append(
                self._make(
                    "FAIL2BAN_NO_ACTIVE_JAILS",
                    "info",
                    "Fail2ban reports no active jails.",
                    evidence=evidence,
                    command=result.get("command"),
                )
            )

    @classmethod
    def _location(cls, evidence: str) -> tuple[str | None, int | None]:
        match = cls.LOCATION_RE.search(evidence)
        if not match:
            return None, None
        return match.group("file"), int(match.group("line"))

    @staticmethod
    def _find_row(files: list[dict], path: str | None, line: int | None) -> dict | None:
        if not path or line is None:
            return None
        for file_data in files:
            if str(file_data.get("file_path")) != path:
                continue
            for row in file_data.get("lines", []):
                if int(row.get("line_number") or 0) == line:
                    return row
        return None

    @staticmethod
    def _filter_exists(config_dir: Path, name: str) -> bool:
        base = config_dir / "filter.d"
        return (base / f"{name}.conf").is_file() or (base / f"{name}.local").is_file()

    @staticmethod
    def _user_override(path: str | None) -> bool:
        if not path:
            return False
        candidate = Path(path)
        if candidate.name in {"jail.conf", "fail2ban.conf"}:
            return False
        if "filter.d" in candidate.parts or "action.d" in candidate.parts:
            return False
        return candidate.suffix == ".local" or "jail.d" in candidate.parts

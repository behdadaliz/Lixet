# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""SSH service inspection."""

from __future__ import annotations

from pathlib import Path

from validators.helpers import run_command


class SSHService:
    """Read and parse an OpenSSH sshd_config file."""

    def __init__(self, config_path: str = "/etc/ssh/sshd_config") -> None:
        self.config_path = config_path

    def inspect(self) -> dict:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"SSH configuration not found: {self.config_path}")
        if not path.is_file():
            raise ValueError(f"SSH configuration is not a file: {self.config_path}")

        parsed_data: list[dict] = []
        in_match = False
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(keepends=True), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                parsed_data.append(self._record(line_number, line, False, None, None, in_match))
                continue

            normalized = stripped.replace("=", " ", 1)
            parts = normalized.split(None, 1)
            directive = parts[0]
            value = parts[1].strip() if len(parts) > 1 else ""
            parsed_data.append(self._record(line_number, line, True, directive, value, in_match))
            if directive.lower() == "match":
                in_match = True

        return {
            "file_path": str(path),
            "lines": parsed_data,
            "config_test": run_command(["sshd", "-t", "-f", self.config_path]),
        }

    @staticmethod
    def _record(
        line_number: int,
        raw_line: str,
        is_active: bool,
        directive: str | None,
        value: str | None,
        in_match: bool,
    ) -> dict:
        return {
            "line_number": line_number,
            "raw_line": raw_line,
            "is_active": is_active,
            "directive": directive,
            "value": value,
            "in_match": in_match,
        }

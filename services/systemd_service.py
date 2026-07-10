# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""systemd runtime, unit, and drop-in inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class SystemdService:
    def __init__(self, config_path: str = "/etc/systemd/system", runner: CommandExecutor | None = None) -> None:
        self.config_path = config_path
        self.runner = runner

    def inspect(self) -> dict:
        root = Path(self.config_path)
        paths = sorted(root.glob("*.service")) if root.is_dir() else ([root] if root.is_file() else [])
        units = [self._unit(path) for path in paths]
        verify_paths = [str(path) for path in paths]
        return {
            "file_path": str(root),
            "units": units,
            "config_absent": not root.exists(),
            "failed_units": run_command(
                ["systemctl", "--failed", "--no-pager", "--plain"], timeout=5, runner=self.runner
            ),
            "system_state": run_command(["systemctl", "is-system-running"], timeout=5, runner=self.runner),
            "config_test": run_command(["systemd-analyze", "verify", *verify_paths], timeout=8, runner=self.runner)
            if verify_paths
            else None,
        }

    @staticmethod
    def _unit(path: Path) -> dict:
        files = [path]
        dropins = path.with_name(path.name + ".d")
        if dropins.is_dir():
            files.extend(sorted(item for item in dropins.glob("*.conf") if item.is_file()))
        parsed = [SystemdService._file(item) for item in files]
        return {
            "file_path": str(path),
            "files": parsed,
            "lines": [row for file_data in parsed for row in file_data["lines"]],
        }

    @staticmethod
    def _file(path: Path) -> dict:
        info = TextFileService(str(path)).inspect()
        section: str | None = None
        rows: list[dict] = []
        for row in info["lines"]:
            text = row["text"]
            if not row["is_active"]:
                rows.append({**row, "section": section, "key": None, "value": None})
                continue
            if text.startswith("[") and text.endswith("]"):
                section = text[1:-1].strip()
                rows.append({**row, "section": section, "key": None, "value": None})
                continue
            key, value = text.split("=", 1) if "=" in text else (text, "")
            rows.append({**row, "section": section, "key": key.strip(), "value": value.strip()})
        return {"file_path": str(path), "snapshot": info["snapshot"], "lines": rows}

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""sudoers configuration inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class SudoersService:
    def __init__(self, config_path: str = "/etc/sudoers", runner: CommandExecutor | None = None) -> None:
        self.config_path = config_path
        self.runner = runner

    def inspect(self) -> dict:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"sudoers file not found: {self.config_path}")
        if not path.is_file():
            raise ValueError(f"sudoers path is not a file: {self.config_path}")
        files = [self._file(path)]
        sudoers_d = path.parent / "sudoers.d"
        if path.name == "sudoers" and sudoers_d.is_dir():
            files.extend(
                self._file(item)
                for item in sorted(sudoers_d.iterdir())
                if item.is_file() and "." not in item.name and not item.name.endswith("~")
            )
        return {
            "file_path": str(path),
            "files": files,
            "config_test": run_command(["visudo", "-cf", str(path)], timeout=5, runner=self.runner),
        }

    @staticmethod
    def _file(path: Path) -> dict:
        info = TextFileService(str(path)).inspect()
        return {"file_path": str(path), "lines": info["lines"], "snapshot": info["snapshot"]}

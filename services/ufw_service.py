# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""UFW configuration inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class UFWService(TextFileService):
    def __init__(self, config_path: str = "/etc/ufw/ufw.conf", runner: CommandExecutor | None = None) -> None:
        super().__init__(config_path)
        self.runner = runner

    def inspect(self) -> dict:
        try:
            data = super().inspect()
        except FileNotFoundError:
            data = {"file_path": self.config_path, "lines": [], "missing_config": True}
        data["files"] = []
        if not data.get("missing_config"):
            data["files"].append(
                {
                    "file_path": data["file_path"],
                    "role": "state",
                    "lines": data["lines"],
                    "snapshot": data.get("snapshot"),
                }
            )
        path = Path(self.config_path)
        if path.name == "ufw.conf" and path.parent.name == "ufw":
            defaults = path.parent.parent / "default" / "ufw"
            if defaults.is_file():
                info = TextFileService(str(defaults)).inspect()
                data["files"].append(
                    {
                        "file_path": info["file_path"],
                        "role": "defaults",
                        "lines": info["lines"],
                        "snapshot": info["snapshot"],
                    }
                )
        data["ufw_status"] = run_command(["ufw", "status"], runner=self.runner)
        return data

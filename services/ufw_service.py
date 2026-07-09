# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""UFW configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from validators.helpers import run_command


class UFWService(TextFileService):
    def __init__(self, config_path: str = "/etc/ufw/ufw.conf") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        try:
            data = super().inspect()
        except FileNotFoundError:
            data = {"file_path": self.config_path, "lines": [], "missing_config": True}
        data["ufw_status"] = run_command(["ufw", "status"])
        return data

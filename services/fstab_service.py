# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""fstab inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from validators.helpers import run_command


class FstabService(TextFileService):
    def __init__(self, config_path: str = "/etc/fstab") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        data = super().inspect()
        data["findmnt_verify"] = run_command(["findmnt", "--verify", "--tab-file", self.config_path], timeout=5)
        return data

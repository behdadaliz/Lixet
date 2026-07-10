# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Basic networking file inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class NetworkingService(TextFileService):
    def __init__(self, config_path: str = "/etc/hosts", runner: CommandExecutor | None = None) -> None:
        super().__init__(config_path)
        self.runner = runner

    def inspect(self) -> dict:
        data = super().inspect()
        data["ip_route"] = run_command(["ip", "route"], timeout=4, runner=self.runner)
        data["ip_addr"] = run_command(["ip", "addr"], timeout=4, runner=self.runner)
        data["ip_link"] = run_command(["ip", "link"], timeout=4, runner=self.runner)
        return data

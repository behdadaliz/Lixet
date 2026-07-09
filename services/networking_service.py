# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Basic networking file inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from validators.helpers import run_command


class NetworkingService(TextFileService):
    def __init__(self, config_path: str = "/etc/hosts") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        data = super().inspect()
        data["ip_route"] = run_command(["ip", "route"], timeout=4)
        data["ip_addr"] = run_command(["ip", "addr"], timeout=4)
        data["ip_link"] = run_command(["ip", "link"], timeout=4)
        return data

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Nginx configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from validators.helpers import run_command


class NginxService(TextFileService):
    def __init__(self, config_path: str = "/etc/nginx/nginx.conf") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        data = super().inspect()
        data["config_test"] = run_command(["nginx", "-t", "-c", self.config_path])
        return data

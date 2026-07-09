# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""DNS resolver configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService
from validators.helpers import run_command


class DNSService(TextFileService):
    def __init__(self, config_path: str = "/etc/resolv.conf") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        data = super().inspect()
        data["resolvectl"] = run_command(["resolvectl", "status"], timeout=4)
        data["getent"] = run_command(["getent", "hosts", "example.com"], timeout=4)
        return data

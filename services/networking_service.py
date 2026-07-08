# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Basic networking file inspection."""

from __future__ import annotations

from services.text_service import TextFileService


class NetworkingService(TextFileService):
    def __init__(self, config_path: str = "/etc/hosts") -> None:
        super().__init__(config_path)

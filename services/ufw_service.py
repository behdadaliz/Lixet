# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""UFW configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService


class UFWService(TextFileService):
    def __init__(self, config_path: str = "/etc/ufw/ufw.conf") -> None:
        super().__init__(config_path)

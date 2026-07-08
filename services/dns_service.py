# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""DNS resolver configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService


class DNSService(TextFileService):
    def __init__(self, config_path: str = "/etc/resolv.conf") -> None:
        super().__init__(config_path)

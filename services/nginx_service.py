# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Nginx configuration inspection."""

from __future__ import annotations

from services.text_service import TextFileService


class NginxService(TextFileService):
    def __init__(self, config_path: str = "/etc/nginx/nginx.conf") -> None:
        super().__init__(config_path)

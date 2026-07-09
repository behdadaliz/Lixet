# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""DNS resolver configuration inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from validators.helpers import run_command


class DNSService(TextFileService):
    def __init__(self, config_path: str = "/etc/resolv.conf") -> None:
        super().__init__(config_path)

    def inspect(self) -> dict:
        path = Path(self.config_path)
        try:
            data = super().inspect()
        except FileNotFoundError:
            data = {"file_path": self.config_path, "lines": [], "missing_config": True}
        data["managed_resolver"] = self._managed_resolver(path)
        data["resolvectl"] = run_command(["resolvectl", "status"], timeout=4)
        data["getent"] = run_command(["getent", "hosts", "example.com"], timeout=4)
        return data

    @staticmethod
    def _managed_resolver(path: Path) -> bool:
        if not path.is_symlink():
            return False
        try:
            target = str(path.readlink())
        except OSError:
            return False
        return "systemd/resolve" in target or "stub-resolv.conf" in target

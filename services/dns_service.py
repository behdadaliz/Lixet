# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""DNS resolver configuration inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class DNSService(TextFileService):
    def __init__(self, config_path: str = "/etc/resolv.conf", runner: CommandExecutor | None = None) -> None:
        super().__init__(config_path)
        self.runner = runner

    def inspect(self) -> dict:
        path = Path(self.config_path)
        try:
            data = super().inspect()
        except FileNotFoundError:
            data = {"file_path": self.config_path, "lines": [], "missing_config": True}
        data["resolver_manager"] = self._resolver_manager(path, data.get("lines", []))
        data["managed_resolver"] = bool(data["resolver_manager"])
        data["resolvectl"] = run_command(["resolvectl", "status"], timeout=4, runner=self.runner)
        return data

    @staticmethod
    def _resolver_manager(path: Path, rows: list[dict]) -> str | None:
        if path.is_symlink():
            try:
                target = str(path.resolve(strict=True)).lower()
            except (OSError, RuntimeError):
                return "unsafe-symlink"
            if "systemd/resolve" in target or "stub-resolv.conf" in target:
                return "systemd-resolved"
            if "networkmanager" in target:
                return "NetworkManager"
            if "resolvconf" in target:
                return "resolvconf"
            return "symlink-managed"
        head = "\n".join(str(item.get("raw_line", "")) for item in rows[:8]).lower()
        if "networkmanager" in head:
            return "NetworkManager"
        if "resolvconf" in head:
            return "resolvconf"
        if "systemd-resolved" in head:
            return "systemd-resolved"
        if "docker" in head or "container" in head:
            return "container-runtime"
        return None

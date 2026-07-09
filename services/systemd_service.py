# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Systemd unit inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService
from validators.helpers import run_command


class SystemdService:
    def __init__(self, config_path: str = "/etc/systemd/system") -> None:
        self.config_path = config_path

    def inspect(self) -> dict:
        root = Path(self.config_path)
        if not root.exists():
            raise FileNotFoundError(f"Systemd path not found: {self.config_path}")
        paths = sorted(root.glob("*.service")) if root.is_dir() else [root]
        if not paths:
            raise FileNotFoundError(f"No service units found in: {self.config_path}")
        return {
            "file_path": str(root),
            "units": [self._unit(path) for path in paths if path.is_file()],
            "failed_units": run_command(["systemctl", "--failed", "--no-pager"], timeout=5),
            "system_state": run_command(["systemctl", "is-system-running"], timeout=5),
        }

    @staticmethod
    def _unit(path: Path) -> dict:
        data = TextFileService._records(path)
        section: str | None = None
        rows: list[dict] = []
        for row in data:
            txt = row["text"]
            if not row["is_active"]:
                rows.append({**row, "section": section, "key": None, "value": None})
                continue
            if txt.startswith("[") and txt.endswith("]"):
                section = txt[1:-1].strip()
                rows.append({**row, "section": section, "key": None, "value": None})
                continue
            key, value = (txt.split("=", 1) + [""])[:2] if "=" in txt else (txt, "")
            rows.append({**row, "section": section, "key": key.strip(), "value": value.strip()})
        return {"file_path": str(path), "lines": rows}

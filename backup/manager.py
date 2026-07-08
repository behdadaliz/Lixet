# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Backup helpers for Lixet."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


class BackupError(RuntimeError):
    """Raised when a configuration file cannot be backed up."""


class BackupManager:
    """Create timestamped backups before any repair is applied."""

    def __init__(self, backup_dir: str | None = None) -> None:
        self.backup_dir = Path(backup_dir) if backup_dir else None

    def create_backup(self, file_path: str) -> str:
        target = Path(file_path)
        if not target.exists():
            raise BackupError(f"File not found: {target}")
        if not target.is_file():
            raise BackupError(f"Not a regular file: {target}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{target.name}.lixet.{timestamp}.bak"
        backup_path = (self.backup_dir / backup_name) if self.backup_dir else target.with_name(backup_name)
        backup_path = self._free_path(backup_path)
        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
        except OSError as exc:
            raise BackupError(f"Could not create backup for {target}: {exc}") from exc
        return str(backup_path)

    def restore_backup(self, backup_path: str, file_path: str) -> bool:
        backup = Path(backup_path)
        target = Path(file_path)
        if not backup.exists() or not backup.is_file():
            raise BackupError(f"Backup not found: {backup}")
        try:
            shutil.copy2(backup, target)
        except OSError as exc:
            raise BackupError(f"Could not restore {target} from {backup}: {exc}") from exc
        return True

    @staticmethod
    def _free_path(path: Path) -> Path:
        if not path.exists():
            return path
        for n in range(1, 1000):
            nxt = path.with_name(f"{path.name}.{n}")
            if not nxt.exists():
                return nxt
        raise BackupError(f"Could not find a free backup name near {path}")

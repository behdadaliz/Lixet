# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Backward-compatible import path for the backup manager."""

from backup.manager import BackupError, BackupManager

__all__ = ["BackupError", "BackupManager"]

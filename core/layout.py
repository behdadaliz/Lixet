# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Central installation and runtime layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LixetLayout:
    install_dir: Path = Path("/opt/lixet")
    bin_path: Path = Path("/usr/local/bin/lixet")
    state_dir: Path = Path("/var/lib/lixet")
    backup_dir: Path = Path("/var/lib/lixet/backups")
    log_dir: Path = Path("/var/log/lixet")
    lock_dir: Path = Path("/run/lock/lixet")

    @property
    def update_lock(self) -> Path:
        return self.lock_dir / "update.lock"


DEFAULT_LAYOUT = LixetLayout()

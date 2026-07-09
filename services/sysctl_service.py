# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""sysctl configuration inspection."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService


class SysctlService:
    def __init__(self, config_path: str = "/etc/sysctl.conf") -> None:
        self.config_path = config_path

    def inspect(self) -> dict:
        main = Path(self.config_path)
        if not main.exists():
            raise FileNotFoundError(f"sysctl configuration not found: {self.config_path}")
        if not main.is_file():
            raise ValueError(f"sysctl configuration is not a file: {self.config_path}")
        files = [self._file(main)]
        conf_dir = main.parent / "sysctl.d"
        if main.name == "sysctl.conf" and conf_dir.is_dir():
            files.extend(self._file(item) for item in sorted(conf_dir.glob("*.conf")) if item.is_file())
        return {"file_path": str(main), "files": files}

    @staticmethod
    def _file(path: Path) -> dict:
        return {"file_path": str(path), "lines": TextFileService._records(path)}

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Text file inspection helpers."""

from __future__ import annotations

from pathlib import Path


class TextFileService:
    """Read a text configuration file and keep line metadata."""

    def __init__(self, config_path: str) -> None:
        self.config_path = config_path

    def inspect(self) -> dict:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration not found: {self.config_path}")
        if not path.is_file():
            raise ValueError(f"Configuration is not a file: {self.config_path}")
        return {"file_path": str(path), "lines": self._records(path)}

    @staticmethod
    def _records(path: Path) -> list[dict]:
        rows: list[dict] = []
        for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(keepends=True), start=1):
            txt = raw.strip()
            rows.append({
                "line_number": n,
                "raw_line": raw,
                "text": txt,
                "is_active": bool(txt and not txt.startswith("#")),
            })
        return rows

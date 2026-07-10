# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Text file inspection helpers."""

from __future__ import annotations

from pathlib import Path

from repair.snapshot import capture_snapshot


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
        snapshot = capture_snapshot(path)
        return {
            "file_path": str(path),
            "resolved_path": snapshot.resolved_path,
            "snapshot": snapshot,
            "lines": self._records(Path(snapshot.resolved_path), str(path)),
        }

    @staticmethod
    def _records(path: Path, display_path: str | None = None) -> list[dict]:
        rows: list[dict] = []
        for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(keepends=True), start=1):
            txt = raw.strip()
            rows.append(
                {
                    "file_path": display_path or str(path),
                    "line_number": n,
                    "raw_line": raw,
                    "text": txt,
                    "is_active": bool(txt and not txt.startswith("#")),
                }
            )
        return rows

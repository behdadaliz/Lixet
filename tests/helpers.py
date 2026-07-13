# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Shared isolated fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from core.install_transaction import MARKER_NAME, PROJECT_ID


def row(number: int, text: str, file_path: str = "/tmp/config") -> dict:
    raw = text if text.endswith(("\n", "\r")) else text + "\n"
    clean = raw.strip()
    return {
        "file_path": file_path,
        "line_number": number,
        "raw_line": raw,
        "text": clean,
        "is_active": bool(clean and not clean.startswith(("#", ";"))),
    }


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], dict] | None = None, available: set[str] | None = None) -> None:
        self.results = results or {}
        self.available = available or set()
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: list[str], _timeout: int = 5) -> dict | None:
        key = tuple(args)
        self.calls.append(key)
        return self.results.get(key)

    def resolve(self, command: str) -> Path | None:
        return Path("/trusted") / command if command in self.available else None


def create_owned_install(root: Path, version: str = "0.3.0-alpha") -> None:
    root.mkdir(parents=True)
    (root / "sentinel").write_text("old", encoding="utf-8")
    marker = {"schema": 1, "project": PROJECT_ID, "transaction_id": "old", "version": version}
    (root / MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")


def create_source_tree(root: Path, version: str = "0.3.0-beta") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
    (root / "main.py").write_text("print('source')\n", encoding="utf-8", newline="\n")
    (root / "install.py").write_text("# installer\n", encoding="utf-8", newline="\n")
    for name in ("cli", "core", "services", "validators", "repair", "backup", "utils"):
        directory = root / name
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")

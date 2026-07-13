# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Unified diff helpers for previewing deterministic repairs."""

from __future__ import annotations

import codecs
import difflib
from dataclasses import dataclass
from pathlib import Path

from repair.manager import RepairManager
from utils.ui import UI


@dataclass(frozen=True)
class DiffFile:
    path: str
    before: bytes | str
    after: bytes | str


def repaired_bytes(original: bytes, fixes: list[dict]) -> bytes:
    bom = codecs.BOM_UTF8 if original.startswith(codecs.BOM_UTF8) else b""
    body = original[len(bom) :] if bom else original
    lines = body.decode("utf-8").splitlines(keepends=True)
    repaired, _messages = RepairManager._apply_to_lines(lines, fixes)
    return bom + "".join(repaired).encode("utf-8")


def repaired_file_bytes(path: str | Path, fixes: list[dict]) -> bytes:
    return repaired_bytes(Path(path).read_bytes(), fixes)


def unified_diff_lines(path: str, before: bytes | str, after: bytes | str) -> list[str]:
    left = _to_text(before).splitlines(keepends=True)
    right = _to_text(after).splitlines(keepends=True)
    return list(
        difflib.unified_diff(
            left,
            right,
            fromfile=f"a/{_display_path(path)}",
            tofile=f"b/{_display_path(path)}",
            lineterm="",
        )
    )


def unified_diff(files: list[DiffFile]) -> list[str]:
    lines: list[str] = []
    for item in files:
        if lines:
            lines.append("")
        lines.extend(unified_diff_lines(item.path, item.before, item.after))
    return lines


def render_plain(files: list[DiffFile]) -> str:
    return "\n".join(UI.clean(line.rstrip("\n\r")) for line in unified_diff(files))


def render_colored(files: list[DiffFile], ui: UI) -> str:
    return "\n".join(_color_line(UI.clean(line.rstrip("\n\r")), ui) for line in unified_diff(files))


def render_diff(files: list[DiffFile], ui: UI | None = None) -> str:
    if ui is None:
        return render_plain(files)
    return render_colored(files, ui)


def _color_line(line: str, ui: UI) -> str:
    if line.startswith("@@"):
        return ui.c(line, ui.CYAN)
    if line.startswith(("---", "+++")):
        return ui.c(line, ui.BOLD + ui.CYAN)
    if line.startswith("+"):
        return ui.c(line, ui.GREEN)
    if line.startswith("-"):
        return ui.c(line, ui.RED)
    return ui.clean(line)


def _to_text(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    bom = codecs.BOM_UTF8 if value.startswith(codecs.BOM_UTF8) else b""
    body = value[len(bom) :] if bom else value
    text = body.decode("utf-8", errors="replace")
    return ("\ufeff" if bom else "") + text


def _display_path(path: str) -> str:
    return UI.clean(str(path).replace("\\", "/")).lstrip("/")

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Bounded Nginx configuration and include inspection."""

from __future__ import annotations

import glob
import re
from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class NginxService:
    MAX_DEPTH = 8
    MAX_FILES = 128

    def __init__(self, config_path: str = "/etc/nginx/nginx.conf", runner: CommandExecutor | None = None) -> None:
        self.config_path = config_path
        self.runner = runner
        self._include_base = Path(config_path).absolute().parent

    def inspect(self) -> dict:
        root = Path(self.config_path).absolute()
        if not root.exists():
            raise FileNotFoundError(f"Nginx configuration not found: {self.config_path}")
        files: list[dict] = []
        errors: list[str] = []
        self._parse(root, 0, tuple(), files, errors)
        lines = [row for file_data in files for row in file_data["lines"]]
        return {
            "file_path": str(root),
            "files": files,
            "lines": lines,
            "include_errors": errors,
            "snapshot": files[0]["snapshot"],
            "config_test": run_command(["nginx", "-t", "-c", str(root)], runner=self.runner),
        }

    def _parse(
        self,
        path: Path,
        depth: int,
        stack: tuple[Path, ...],
        files: list[dict],
        errors: list[str],
    ) -> None:
        if depth > self.MAX_DEPTH:
            errors.append(f"Nginx include depth exceeds {self.MAX_DEPTH}: {path}")
            return
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            errors.append(f"Cannot resolve Nginx include {path}: {exc}")
            return
        if resolved in stack:
            errors.append(f"Nginx include cycle detected: {resolved}")
            return
        if len(files) >= self.MAX_FILES:
            errors.append(f"Nginx include file limit exceeds {self.MAX_FILES}")
            return
        if not resolved.is_file():
            errors.append(f"Nginx include is not a regular file: {resolved}")
            return

        info = TextFileService(str(path)).inspect()
        files.append(info)
        next_stack = (*stack, resolved)
        for row in info["lines"]:
            clean = self._without_comment(str(row["raw_line"]))
            match = re.match(r"^\s*include\s+(.+?)\s*;\s*$", clean)
            if not match:
                continue
            pattern = match.group(1).strip().strip("'\"")
            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = self._include_base / candidate
            for item in sorted(glob.glob(str(candidate))):
                self._parse(Path(item), depth + 1, next_stack, files, errors)

    @staticmethod
    def _without_comment(text: str) -> str:
        quote: str | None = None
        escaped = False
        output: list[str] = []
        for char in text:
            if escaped:
                output.append(char)
                escaped = False
                continue
            if char == "\\":
                output.append(char)
                escaped = True
                continue
            if quote:
                output.append(char)
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
                output.append(char)
                continue
            if char == "#":
                break
            output.append(char)
        return "".join(output)

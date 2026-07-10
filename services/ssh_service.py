# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Bounded OpenSSH configuration inspection."""

from __future__ import annotations

import glob
import shlex
from pathlib import Path

from repair.snapshot import capture_snapshot
from utils.command import CommandExecutor
from validators.helpers import run_command


class SSHService:
    MAX_DEPTH = 8
    MAX_FILES = 64

    def __init__(self, config_path: str = "/etc/ssh/sshd_config", runner: CommandExecutor | None = None) -> None:
        self.config_path = config_path
        self.runner = runner
        self._include_base = Path(config_path).absolute().parent

    def inspect(self) -> dict:
        root = Path(self.config_path).absolute()
        if not root.exists():
            raise FileNotFoundError(f"SSH configuration not found: {self.config_path}")
        if not root.is_file():
            raise ValueError(f"SSH configuration is not a file: {self.config_path}")

        files: list[dict] = []
        merged: list[dict] = []
        errors: list[str] = []
        self._parse(root, False, 0, tuple(), files, merged, errors)
        return {
            "file_path": str(root),
            "files": files,
            "lines": merged,
            "include_errors": errors,
            "snapshot": files[0]["snapshot"],
            "config_test": run_command(["sshd", "-t", "-f", str(root)], runner=self.runner),
            "effective_config": run_command(["sshd", "-T", "-f", str(root)], runner=self.runner),
        }

    def _parse(
        self,
        path: Path,
        in_match: bool,
        depth: int,
        stack: tuple[Path, ...],
        files: list[dict],
        merged: list[dict],
        errors: list[str],
    ) -> bool:
        if depth > self.MAX_DEPTH:
            errors.append(f"SSH include depth exceeds {self.MAX_DEPTH}: {path}")
            return in_match
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            errors.append(f"Cannot resolve SSH include {path}: {exc}")
            return in_match
        if resolved in stack:
            errors.append(f"SSH include cycle detected: {resolved}")
            return in_match
        if len(files) >= self.MAX_FILES:
            errors.append(f"SSH include file limit exceeds {self.MAX_FILES}")
            return in_match
        if not resolved.is_file():
            errors.append(f"SSH include is not a regular file: {resolved}")
            return in_match

        snapshot = capture_snapshot(path)
        rows: list[dict] = []
        files.append({"file_path": str(path), "resolved_path": str(resolved), "snapshot": snapshot, "lines": rows})
        try:
            content = resolved.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        except OSError as exc:
            errors.append(f"Cannot read SSH include {path}: {exc}")
            return in_match

        next_stack = (*stack, resolved)
        for line_number, raw in enumerate(content, start=1):
            stripped = raw.strip()
            directive: str | None = None
            value: str | None = None
            active = bool(stripped and not stripped.startswith("#"))
            if active:
                normalized = stripped.replace("=", " ", 1)
                parts = normalized.split(None, 1)
                directive = parts[0]
                value = parts[1].strip() if len(parts) > 1 else ""
            record = {
                "file_path": str(path),
                "line_number": line_number,
                "raw_line": raw,
                "text": stripped,
                "is_active": active,
                "directive": directive,
                "value": value,
                "in_match": in_match,
            }
            rows.append(record)
            merged.append(record)
            if not directive:
                continue
            name = directive.lower()
            if name == "match":
                in_match = True
            elif name == "include" and value:
                for include in self._includes(value):
                    in_match = self._parse(include, in_match, depth + 1, next_stack, files, merged, errors)
        return in_match

    def _includes(self, value: str) -> list[Path]:
        try:
            patterns = shlex.split(value, comments=False, posix=True)
        except ValueError:
            patterns = value.split()
        found: list[Path] = []
        for pattern in patterns:
            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = self._include_base / candidate
            found.extend(Path(item) for item in sorted(glob.glob(str(candidate))))
        return found

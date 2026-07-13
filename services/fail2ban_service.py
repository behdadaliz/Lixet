# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Fail2ban configuration inspection."""

from __future__ import annotations

import shlex
from pathlib import Path

from services.text_service import TextFileService
from utils.command import CommandExecutor
from validators.helpers import run_command


class Fail2banService:
    MAX_DEPTH = 8
    MAX_FILES = 160

    MAIN_ORDER = ("fail2ban.conf", "fail2ban.local", "jail.conf", "jail.local")

    def __init__(self, config_path: str = "/etc/fail2ban", runner: CommandExecutor | None = None) -> None:
        self.config_path = config_path
        self.runner = runner
        self._seen: set[Path] = set()

    def inspect(self) -> dict:
        target = Path(self.config_path)
        if not target.exists():
            raise FileNotFoundError(f"Fail2ban configuration not found: {self.config_path}")
        config_dir = target if target.is_dir() else self._config_dir(target)
        files: list[dict] = []
        errors: list[str] = []
        roots = self._roots(target, config_dir)
        for path in roots:
            self._parse(path, config_dir, 0, tuple(), files, errors)
        lines = [row for file_data in files for row in file_data["lines"]]
        return {
            "file_path": str(target),
            "config_dir": str(config_dir),
            "files": files,
            "lines": lines,
            "include_errors": errors,
            "missing_config": False,
            "config_test": run_command(["fail2ban-client", "-t", "-c", str(config_dir)], timeout=8, runner=self.runner),
            "runtime_status": run_command(["fail2ban-client", "status"], timeout=5, runner=self.runner),
        }

    def _roots(self, target: Path, config_dir: Path) -> list[Path]:
        if target.is_file():
            return [target]
        if not target.is_dir():
            raise ValueError(f"Fail2ban target is not a file or directory: {self.config_path}")
        found: list[Path] = []
        for name in self.MAIN_ORDER:
            path = config_dir / name
            if path.is_file():
                found.append(path)
        for directory, patterns in (
            ("jail.d", ("*.conf", "*.local")),
            ("filter.d", ("*.local",)),
            ("action.d", ("*.local",)),
        ):
            root = config_dir / directory
            if not root.is_dir():
                continue
            for pattern in patterns:
                found.extend(sorted(item for item in root.glob(pattern) if item.is_file()))
        return self._dedupe(found)

    def _parse(
        self,
        path: Path,
        config_dir: Path,
        depth: int,
        stack: tuple[Path, ...],
        files: list[dict],
        errors: list[str],
    ) -> None:
        if depth > self.MAX_DEPTH:
            errors.append(f"Fail2ban include depth exceeds {self.MAX_DEPTH}: {path}")
            return
        if len(files) >= self.MAX_FILES:
            errors.append(f"Fail2ban file limit exceeds {self.MAX_FILES}")
            return
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            errors.append(f"Cannot resolve Fail2ban include {path}: {exc}")
            return
        if resolved in stack:
            errors.append(f"Fail2ban include cycle detected: {resolved}")
            return
        if resolved in self._seen:
            return
        if not resolved.is_file():
            errors.append(f"Fail2ban include is not a regular file: {resolved}")
            return
        self._seen.add(resolved)
        try:
            info = TextFileService(str(path)).inspect()
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"Cannot read Fail2ban include {path}: {exc}")
            return
        files.append(info)
        next_stack = (*stack, resolved)
        for include in self._includes(info["lines"], resolved.parent, config_dir):
            if not include.exists():
                errors.append(f"Fail2ban include is missing: {include}")
                continue
            self._parse(include, config_dir, depth + 1, next_stack, files, errors)

    @staticmethod
    def _includes(rows: list[dict], current_dir: Path, config_dir: Path) -> list[Path]:
        in_includes = False
        found: list[Path] = []
        for row in rows:
            text = str(row.get("text") or "")
            if not text or text.startswith(("#", ";")):
                continue
            if text.startswith("[") and text.endswith("]"):
                in_includes = text[1:-1].strip().lower() == "includes"
                continue
            if not in_includes or "=" not in text:
                continue
            key, value = text.split("=", 1)
            if key.strip().lower() not in {"before", "after"}:
                continue
            for part in _split_list(value):
                candidate = Path(part)
                if not candidate.is_absolute():
                    candidate = current_dir / candidate
                    if not candidate.exists():
                        candidate = config_dir / part
                found.append(candidate)
        return found

    @staticmethod
    def _config_dir(path: Path) -> Path:
        parts = path.parts
        if "fail2ban" in parts:
            index = parts.index("fail2ban")
            return Path(*parts[: index + 1])
        return path.parent

    @staticmethod
    def _dedupe(paths: list[Path]) -> list[Path]:
        seen: set[Path] = set()
        result: list[Path] = []
        for path in paths:
            try:
                key = path.resolve(strict=False)
            except RuntimeError:
                key = path.absolute()
            if key not in seen:
                seen.add(key)
                result.append(path)
        return result


def _split_list(value: str) -> list[str]:
    try:
        return shlex.split(value, comments=True, posix=True)
    except ValueError:
        return value.split()

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Trusted, bounded execution of system inspection commands."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

DEFAULT_TIMEOUT = 5
MAX_OUTPUT = 64 * 1024
POSIX_TRUSTED_DIRS = ("/usr/sbin", "/usr/bin", "/sbin", "/bin", "/usr/local/sbin", "/usr/local/bin")


class CommandExecutor(Protocol):
    def resolve(self, command: str) -> Path | None: ...

    def run(self, args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict | None: ...


class CommandRunner:
    def __init__(
        self,
        trusted_dirs: Iterable[str | Path] | None = None,
        require_root_owner: bool | None = None,
        max_output: int = MAX_OUTPUT,
    ) -> None:
        if trusted_dirs is None:
            if os.name == "posix":
                trusted_dirs = POSIX_TRUSTED_DIRS
            else:
                system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
                trusted_dirs = (system_root / "System32",)
        self.trusted_dirs = tuple(Path(item).resolve(strict=False) for item in trusted_dirs)
        self.require_root_owner = os.name == "posix" if require_root_owner is None else require_root_owner
        self.max_output = max_output

    def resolve(self, command: str) -> Path | None:
        candidate = Path(command)
        paths: tuple[Path, ...]
        if candidate.is_absolute():
            paths = (candidate,)
        elif candidate.name != command:
            return None
        else:
            names = [command]
            if os.name == "nt" and not Path(command).suffix:
                names.extend(command + ext.lower() for ext in os.environ.get("PATHEXT", ".EXE").split(os.pathsep))
            paths = tuple(root / name for root in self.trusted_dirs for name in names)

        for path in paths:
            if self._trusted(path):
                return path.resolve(strict=True)
        return None

    def run(self, args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict | None:
        if not args:
            return None
        executable = self.resolve(args[0])
        if executable is None:
            return None

        command = [str(executable), *[str(item) for item in args[1:]]]
        shown = shlex.join(command)
        env = {
            "PATH": os.pathsep.join(str(path) for path in self.trusted_dirs),
            "LC_ALL": "C",
            "LANG": "C",
            "TERM": "dumb",
        }
        if os.name == "nt" and "SystemRoot" in os.environ:
            env["SystemRoot"] = os.environ["SystemRoot"]

        timed_out = False
        returncode = 126
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    env=env,
                    close_fds=True,
                )
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    process.wait()
                    returncode = 124
                out = self._read_limited(stdout)
                err = self._read_limited(stderr)
        except OSError as exc:
            return {
                "returncode": 126,
                "evidence": f"Could not run command {shown}: {exc}",
                "command": shown,
                "timeout": False,
                "error_kind": "execution",
            }

        evidence = "\n".join(part.strip() for part in (out, err) if part.strip())
        if timed_out:
            prefix = f"Command timed out after {timeout}s: {shown}"
            evidence = f"{prefix}\n{evidence}" if evidence else prefix
        return {
            "returncode": returncode,
            "evidence": evidence,
            "command": shown,
            "timeout": timed_out,
            "error_kind": "timeout" if timed_out else None,
        }

    def _trusted(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            return False
        if not resolved.is_file():
            return False
        if os.name == "posix" and not os.access(resolved, os.X_OK):
            return False
        if not any(_is_relative_to(resolved, root) for root in self.trusted_dirs):
            return False
        if os.name == "posix":
            if self.require_root_owner and getattr(info, "st_uid", -1) != 0:
                return False
            if stat.S_IMODE(info.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
                return False
            for parent in (resolved.parent, *resolved.parents):
                try:
                    parent_info = parent.stat()
                    if self.require_root_owner and getattr(parent_info, "st_uid", -1) != 0:
                        return False
                    if stat.S_IMODE(parent_info.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
                        return False
                except OSError:
                    return False
                if parent in self.trusted_dirs:
                    break
        return True

    def _read_limited(self, stream) -> str:
        stream.seek(0)
        data = stream.read(self.max_output + 1)
        truncated = len(data) > self.max_output
        data = data[: self.max_output]
        text = data.decode("utf-8", errors="replace")
        if truncated:
            text += "\n[output truncated by Lixet]"
        return text


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

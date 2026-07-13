# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Transactional installation shared by the installer and updater."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from core.version import parse_version

PROJECT_ID = "github.com/behdadaliz/Lixet"
MARKER_NAME = ".lixet-install.json"
REQUIRED_FILES = ("VERSION", "main.py", "install.py")
REQUIRED_DIRS = ("cli", "core", "services", "validators", "repair", "backup", "utils")
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".venv",
    "venv",
    "env",
    "developer",
    "docker",
    ".agent",
    ".agents",
    ".codex",
    "build",
    "dist",
    "htmlcov",
}
SKIP_NAMES = {".env"}


class InstallError(RuntimeError):
    """Raised when an installation phase cannot complete safely."""


class InstallRollbackError(InstallError):
    """Raised when the previous installation cannot be restored."""


class InstallPhase(str, Enum):
    SOURCE_VALIDATED = "source validated"
    STAGED = "source staged"
    STAGE_VALIDATED = "stage validated"
    PREVIOUS_BACKED_UP = "previous installation backed up"
    INSTALL_SWAPPED = "new installation swapped"
    COMMAND_LINKED = "command linked"
    COMPLETE = "complete"


class InstallTransaction:
    def __init__(
        self,
        source_dir: str | Path,
        install_dir: str | Path = "/opt/lixet",
        bin_path: str | Path = "/usr/local/bin/lixet",
        force: bool = False,
        phase_hook: Callable[[InstallPhase], None] | None = None,
    ) -> None:
        self.source_dir = Path(source_dir).resolve()
        self.install_dir = Path(install_dir).absolute()
        self.bin_path = Path(bin_path).absolute()
        self.force = force
        self.phase_hook = phase_hook
        self.transaction_id = uuid.uuid4().hex
        self.stage: Path | None = None
        self.backup: Path | None = None
        self.old_link: str | None = None
        self.old_command_backup: Path | None = None
        self.old_link_existed = False
        self.link_recorded = False
        self.swapped = False
        self.linked = False

    def install(self) -> None:
        self._validate_tree(self.source_dir)
        self._phase(InstallPhase.SOURCE_VALIDATED)
        self._check_ownership()
        self.install_dir.parent.mkdir(parents=True, exist_ok=True)
        self.stage = Path(tempfile.mkdtemp(prefix=".lixet-install-", dir=self.install_dir.parent))
        try:
            self._copy_tree(self.source_dir, self.stage)
            self._write_marker(self.stage)
            self._make_executable(self.stage / "main.py")
            self._phase(InstallPhase.STAGED)
            self._validate_tree(self.stage, require_marker=True)
            self._phase(InstallPhase.STAGE_VALIDATED)
            self._remember_link()
            if self.install_dir.exists() or self.install_dir.is_symlink():
                if self.install_dir.is_symlink() or not self.install_dir.is_dir():
                    raise InstallError(f"Install target is not a directory: {self.install_dir}")
                self.backup = self.install_dir.with_name(f".lixet-install-backup-{uuid.uuid4().hex}")
                os.replace(self.install_dir, self.backup)
                self._phase(InstallPhase.PREVIOUS_BACKED_UP)
            os.replace(self.stage, self.install_dir)
            self.stage = None
            self.swapped = True
            self._phase(InstallPhase.INSTALL_SWAPPED)
            self._link_command(self.install_dir / "main.py")
            self.linked = True
            self._phase(InstallPhase.COMMAND_LINKED)
            self._validate_tree(self.install_dir, require_marker=True)
            self._phase(InstallPhase.COMPLETE)
        except BaseException as exc:
            rollback_error = self._rollback()
            if rollback_error:
                raise InstallRollbackError(rollback_error) from exc
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, InstallError):
                raise
            raise InstallError(str(exc)) from exc
        else:
            if self.backup and self.backup.exists():
                shutil.rmtree(self.backup)
                self.backup = None
            if self.old_command_backup and self.old_command_backup.exists():
                self.old_command_backup.unlink()
                self.old_command_backup = None
        finally:
            if self.stage and self.stage.exists() and self._created_stage(self.stage):
                shutil.rmtree(self.stage, ignore_errors=True)
                self.stage = None

    def uninstall(self) -> None:
        if self.install_dir.exists() and not self._owned_install(self.install_dir) and not self.force:
            raise InstallError(f"Refusing to remove unowned directory: {self.install_dir}")
        if (self.bin_path.exists() or self.bin_path.is_symlink()) and not self._owned_command() and not self.force:
            raise InstallError(f"Refusing to remove unrelated command entry: {self.bin_path}")
        if self.bin_path.exists() or self.bin_path.is_symlink():
            if self.bin_path.is_dir() and not self.bin_path.is_symlink():
                raise InstallError(f"Refusing to remove command directory: {self.bin_path}")
            self.bin_path.unlink()
        if self.install_dir.exists():
            shutil.rmtree(self.install_dir)

    def _check_ownership(self) -> None:
        if self.install_dir.exists() or self.install_dir.is_symlink():
            if not self._owned_install(self.install_dir) and not self.force:
                raise InstallError(f"Refusing to overwrite unowned install directory: {self.install_dir}")
        if self.bin_path.exists() or self.bin_path.is_symlink():
            if not self._owned_command() and not self.force:
                raise InstallError(f"Refusing to overwrite unrelated command entry: {self.bin_path}")

    def _rollback(self) -> str | None:
        failures: list[str] = []
        if self.swapped and self.install_dir.exists():
            if self._marker_transaction(self.install_dir) == self.transaction_id:
                try:
                    shutil.rmtree(self.install_dir)
                except OSError as exc:
                    failures.append(f"cannot remove failed installation: {exc}")
            else:
                failures.append("refusing to remove installation not created by this transaction")
        if self.backup and self.backup.exists():
            try:
                if self.install_dir.exists():
                    failures.append("install path is occupied during rollback")
                else:
                    os.replace(self.backup, self.install_dir)
                    self.backup = None
            except OSError as exc:
                failures.append(f"cannot restore previous installation: {exc}")
        try:
            self._restore_link()
        except OSError as exc:
            failures.append(f"cannot restore command entry: {exc}")
        return "; ".join(failures) if failures else None

    def _remember_link(self) -> None:
        self.old_link_existed = self.bin_path.exists() or self.bin_path.is_symlink()
        if self.bin_path.is_symlink():
            self.old_link = os.readlink(self.bin_path)
        elif self.bin_path.exists():
            if not self.bin_path.is_file():
                raise InstallError(f"Command entry is not a regular file or symlink: {self.bin_path}")
            self.old_command_backup = self.bin_path.with_name(f".{self.bin_path.name}.{uuid.uuid4().hex}.backup")
            shutil.copy2(self.bin_path, self.old_command_backup)
        self.link_recorded = True

    def _restore_link(self) -> None:
        if not self.link_recorded:
            return
        if self.old_command_backup and self.old_command_backup.exists():
            os.replace(self.old_command_backup, self.bin_path)
            self.old_command_backup = None
        elif self.old_link_existed and self.old_link is not None:
            self._atomic_symlink(self.old_link)
        elif not self.old_link_existed and (self.bin_path.exists() or self.bin_path.is_symlink()):
            if self.bin_path.is_symlink() and self._link_points_into_install(self.bin_path):
                self.bin_path.unlink()

    def _link_command(self, main_script: Path) -> None:
        self.bin_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_symlink(str(main_script))

    def _atomic_symlink(self, target: str) -> None:
        temp_link = self.bin_path.with_name(f".{self.bin_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_link.symlink_to(target)
            os.replace(temp_link, self.bin_path)
        finally:
            if temp_link.is_symlink() or temp_link.exists():
                temp_link.unlink(missing_ok=True)

    def _owned_command(self) -> bool:
        return self.bin_path.is_symlink() and self._link_points_into_install(self.bin_path)

    def _link_points_into_install(self, path: Path) -> bool:
        try:
            raw = Path(os.readlink(path))
            target = raw if raw.is_absolute() else path.parent / raw
            target.resolve(strict=False).relative_to(self.install_dir.resolve(strict=False))
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        for item in source.iterdir():
            if _skip(item):
                continue
            target = destination / item.name
            if item.is_symlink():
                raise InstallError(f"Source tree contains a symlink: {item}")
            if item.is_dir():
                target.mkdir()
                InstallTransaction._copy_tree(item, target)
            elif item.is_file():
                shutil.copy2(item, target)
            else:
                raise InstallError(f"Source tree contains a special file: {item}")

    def _write_marker(self, root: Path) -> None:
        marker = {
            "schema": 1,
            "project": PROJECT_ID,
            "transaction_id": self.transaction_id,
            "version": (root / "VERSION").read_text(encoding="utf-8").strip(),
        }
        path = root / MARKER_NAME
        path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        if os.name == "posix":
            path.chmod(0o600)

    @staticmethod
    def _validate_tree(root: Path, require_marker: bool = False) -> None:
        for name in REQUIRED_FILES:
            if not (root / name).is_file() or (root / name).is_symlink():
                raise InstallError(f"Required regular file is missing or unsafe: {name}")
        for name in REQUIRED_DIRS:
            if not (root / name).is_dir() or (root / name).is_symlink():
                raise InstallError(f"Required directory is missing or unsafe: {name}")
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        if parse_version(version) is None:
            raise InstallError("VERSION is not valid Semantic Versioning")
        if require_marker and not InstallTransaction._owned_install(root):
            raise InstallError("Installation ownership marker is missing or invalid")

    @staticmethod
    def _owned_install(root: Path) -> bool:
        marker = root / MARKER_NAME
        try:
            if not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 16 * 1024:
                return False
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(data, dict) and data.get("project") == PROJECT_ID and data.get("schema") == 1

    @staticmethod
    def _marker_transaction(root: Path) -> str | None:
        try:
            data = json.loads((root / MARKER_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return str(data.get("transaction_id")) if isinstance(data, dict) else None

    @staticmethod
    def _make_executable(path: Path) -> None:
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _created_stage(self, path: Path) -> bool:
        return path.parent == self.install_dir.parent and path.name.startswith(".lixet-install-")

    def _phase(self, phase: InstallPhase) -> None:
        if self.phase_hook:
            self.phase_hook(phase)


def _skip(path: Path) -> bool:
    name = path.name
    if name in SKIP_DIRS or name in SKIP_NAMES:
        return True
    if name in {".coverage", "coverage.xml", ".DS_Store", "Thumbs.db"}:
        return True
    if name.endswith(
        (".pyc", ".pyo", ".bak", ".tmp", ".temp", ".zip", ".tar", ".tar.gz", ".tgz", ".log", ".egg-info")
    ) or name.startswith(".env."):
        return True
    if ".lixet." in name and name.endswith(".bak"):
        return True
    return False

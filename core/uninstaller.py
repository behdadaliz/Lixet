# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Safe removal of installed Lixet files while preserving backups."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.install_transaction import InstallError, InstallTransaction
from core.layout import DEFAULT_LAYOUT, LixetLayout
from core.models import ExitCode
from utils.ui import UI


class UninstallError(RuntimeError):
    """Raised when uninstall cannot proceed safely."""


class LixetUninstaller:
    def __init__(
        self,
        layout: LixetLayout = DEFAULT_LAYOUT,
        dry_run: bool = False,
        no_color: bool = False,
        ui: UI | None = None,
    ) -> None:
        self.layout = layout
        self.dry_run = dry_run
        self.ui = ui or UI(no_color=no_color)
        self.preserved_backups = layout.backup_dir

    def run(self) -> ExitCode:
        self.ui.banner("Lixet Uninstall")
        try:
            plan = self.plan()
            self._show_plan(plan)
            if self.dry_run:
                self.ui.status("warn", "Dry-run complete. Nothing was removed.")
                self._show_backups()
                return ExitCode.OK
            self._require_root_if_needed(plan)
            if not self.ui.can_prompt():
                self.ui.status("error", "Uninstall requires an interactive terminal. Use --dry-run to preview.")
                return ExitCode.REPAIR_FAILED
            if self.ui.prompt("Type UNINSTALL to continue: ").strip() != "UNINSTALL":
                self.ui.status("info", "Uninstall canceled.")
                self._show_backups()
                return ExitCode.ISSUES
            self.apply(plan)
        except (OSError, UninstallError, InstallError) as exc:
            self.ui.status("error", f"Uninstall failed: {exc}")
            return ExitCode.REPAIR_FAILED
        self.ui.status("ok", "Lixet uninstalled successfully.")
        self._show_backups()
        return ExitCode.OK

    def plan(self) -> list[Path]:
        plan: list[Path] = []
        if self.layout.bin_path.exists() or self.layout.bin_path.is_symlink():
            if not self._owned_command(self.layout.bin_path, self.layout.install_dir):
                raise UninstallError(f"Refusing to remove unrelated command entry: {self.layout.bin_path}")
            plan.append(self.layout.bin_path)
        if self.layout.install_dir.exists() or self.layout.install_dir.is_symlink():
            if self.layout.install_dir.is_symlink() or not InstallTransaction._owned_install(self.layout.install_dir):
                raise UninstallError(f"Refusing to remove unowned install directory: {self.layout.install_dir}")
            plan.append(self.layout.install_dir)
        for path in (self.layout.log_dir, self.layout.lock_dir):
            if path.exists() or path.is_symlink():
                plan.append(path)
        if self.layout.state_dir.exists() or self.layout.state_dir.is_symlink():
            plan.extend(self._state_children())
            if not self._has_backups():
                plan.append(self.layout.state_dir)
        return self._dedupe(plan)

    def apply(self, plan: list[Path]) -> None:
        for path in sorted(plan, key=lambda item: len(item.parts), reverse=True):
            if self._is_backup_path(path):
                continue
            self._remove_owned(path)
        self._remove_empty_lixet_dirs()

    def _state_children(self) -> list[Path]:
        if self.layout.state_dir.is_symlink() or not self.layout.state_dir.is_dir():
            return [self.layout.state_dir]
        found: list[Path] = []
        for child in self.layout.state_dir.iterdir():
            if self._is_backup_path(child):
                continue
            found.append(child)
        return found

    def _remove_owned(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        self._ensure_within_known_root(path)
        if path.is_symlink() or path.is_file():
            path.unlink()
            return
        if path.is_dir():
            shutil.rmtree(path)
            return
        raise UninstallError(f"Refusing to remove special file: {path}")

    def _remove_empty_lixet_dirs(self) -> None:
        for path in (self.layout.lock_dir, self.layout.log_dir, self.layout.state_dir):
            if path.exists() and path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()

    def _ensure_within_known_root(self, path: Path) -> None:
        known = (
            self.layout.install_dir,
            self.layout.bin_path,
            self.layout.state_dir,
            self.layout.log_dir,
            self.layout.lock_dir,
        )
        resolved = path.resolve(strict=False)
        for root in known:
            root_resolved = root.resolve(strict=False)
            if resolved == root_resolved or _relative_to(resolved, root_resolved):
                return
        raise UninstallError(f"Refusing to remove unknown path: {path}")

    def _require_root_if_needed(self, plan: list[Path]) -> None:
        if not plan or os.name != "posix":
            return
        root_paths = (
            Path("/opt"),
            Path("/usr/local/bin"),
            Path("/var/lib/lixet"),
            Path("/var/log/lixet"),
            Path("/run/lock/lixet"),
        )
        if any(_relative_to(path.absolute(), root) or path.absolute() == root for path in plan for root in root_paths):
            if getattr(os, "geteuid", lambda: -1)() != 0:
                raise UninstallError("Uninstall requires root privileges. Try: sudo lixet uninstall")

    def _show_plan(self, plan: list[Path]) -> None:
        self.ui.kv("Preserved backups", str(self.preserved_backups))
        if not plan:
            self.ui.status("info", "No installed Lixet-owned files were found.")
            return
        self.ui.section("Will remove")
        for path in plan:
            if not self._is_backup_path(path):
                self.ui.bullet(str(path))

    def _show_backups(self) -> None:
        if self._has_backups():
            self.ui.status("info", f"Backups preserved: {self.preserved_backups}")

    def _has_backups(self) -> bool:
        return self.layout.backup_dir.exists() or self.layout.backup_dir.is_symlink()

    def _is_backup_path(self, path: Path) -> bool:
        backup = self.layout.backup_dir.resolve(strict=False)
        target = path.resolve(strict=False)
        return target == backup or _relative_to(target, backup)

    @staticmethod
    def _owned_command(bin_path: Path, install_dir: Path) -> bool:
        if not bin_path.is_symlink():
            return False
        try:
            raw = Path(os.readlink(bin_path))
            target = raw if raw.is_absolute() else bin_path.parent / raw
            target.resolve(strict=False).relative_to(install_dir.resolve(strict=False))
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _dedupe(paths: list[Path]) -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path)
            if key not in seen:
                seen.add(key)
                result.append(path)
        return result


def _relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

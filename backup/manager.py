# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Protected backup bundles and verified rollback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repair.snapshot import FileSnapshot, SnapshotError, capture_snapshot
from core.layout import DEFAULT_LAYOUT
from utils.ui import UI


class BackupError(RuntimeError):
    """Raised when a backup cannot be created or restored."""


class RollbackError(BackupError):
    """Raised when a rollback cannot be completed and verified."""


@dataclass(frozen=True)
class BackupListItem:
    backup_id: str
    manifest_path: str
    metadata: dict | None = None
    error: str | None = None


class BackupManager:
    """Create protected manifest-based backups outside configuration trees."""

    DEFAULT_DIR = DEFAULT_LAYOUT.backup_dir
    ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}$")

    def __init__(self, backup_dir: str | Path | None = None) -> None:
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.DEFAULT_DIR

    def create_backup(
        self,
        file_path: str,
        service: str = "unknown",
        repair_ids: list[str] | None = None,
        snapshot: FileSnapshot | None = None,
    ) -> str:
        try:
            snap = snapshot or capture_snapshot(file_path)
        except SnapshotError as exc:
            raise BackupError(str(exc)) from exc
        self._prepare_root()
        backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8)
        bundle = self.backup_dir / backup_id
        try:
            bundle.mkdir(mode=0o700)
            content = Path(snap.resolved_path).read_bytes()
            content_path = bundle / "content"
            self._write_file(content_path, content, 0o600)
            manifest = {
                "schema": 1,
                "backup_id": backup_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_path": snap.original_path,
                "resolved_path": snap.resolved_path,
                "is_symlink": snap.is_symlink,
                "symlink_target": snap.symlink_target,
                "sha256": snap.sha256,
                "uid": snap.uid,
                "gid": snap.gid,
                "mode": snap.mode,
                "mtime_ns": snap.mtime_ns,
                "atime_ns": snap.atime_ns,
                "device": snap.device,
                "inode": snap.inode,
                "service": service,
                "repair_ids": list(repair_ids or []),
                "verification": "pending",
            }
            manifest_path = bundle / "manifest.json"
            payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self._write_file(manifest_path, payload, 0o600)
            return str(manifest_path)
        except OSError as exc:
            raise BackupError(f"Could not create backup for {file_path}: {exc}") from exc

    def restore_backup(self, backup_path: str, file_path: str | None = None) -> bool:
        manifest_path, manifest = self._load_manifest(backup_path)
        original = Path(str(manifest["original_path"]))
        if file_path is not None and original != Path(file_path).absolute():
            raise RollbackError("Backup target does not match requested restore path")
        content_path = manifest_path.parent / "content"
        try:
            content = content_path.read_bytes()
        except OSError as exc:
            raise RollbackError(f"Cannot read backup content: {exc}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest != manifest.get("sha256"):
            raise RollbackError("Backup content hash does not match its manifest")

        resolved = Path(str(manifest["resolved_path"]))
        try:
            self._atomic_restore(resolved, content, manifest)
            if bool(manifest.get("is_symlink")):
                expected_link = str(manifest.get("symlink_target") or "")
                if not original.is_symlink() or os.readlink(original) != expected_link:
                    if original.exists() or original.is_symlink():
                        if original.is_dir() and not original.is_symlink():
                            raise RollbackError(f"Cannot replace directory while restoring symlink: {original}")
                        original.unlink()
                    original.symlink_to(expected_link)
            restored = capture_snapshot(original)
        except (OSError, SnapshotError, RollbackError) as exc:
            if isinstance(exc, RollbackError):
                raise
            raise RollbackError(f"Could not restore {original}: {exc}") from exc
        if restored.sha256 != manifest["sha256"]:
            raise RollbackError(f"Restored content verification failed: {original}")
        if restored.is_symlink != bool(manifest.get("is_symlink")):
            raise RollbackError(f"Restored symlink state verification failed: {original}")
        return True

    def update_verification(self, backup_path: str, state: str) -> None:
        manifest_path, manifest = self._load_manifest(backup_path)
        manifest["verification"] = state
        payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        self._write_file(manifest_path, payload, 0o600)

    def list_backups(self) -> list[BackupListItem]:
        try:
            root = self.backup_dir.resolve(strict=True)
        except OSError:
            return []
        if not root.is_dir() or root.is_symlink():
            raise BackupError(f"Unsafe backup directory: {self.backup_dir}")
        items: list[BackupListItem] = []
        for bundle in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
            if not bundle.is_dir() or not self.ID_RE.fullmatch(bundle.name):
                continue
            manifest = bundle / "manifest.json"
            try:
                metadata = self.load_public_metadata(bundle.name)
                items.append(BackupListItem(bundle.name, str(manifest), metadata, None))
            except BackupError as exc:
                items.append(BackupListItem(bundle.name, str(manifest), None, UI.clean(str(exc))))
        return items

    def load_public_metadata(self, backup_id: str) -> dict:
        manifest_path, manifest = self._load_manifest(backup_id)
        public = {
            "backup_id": manifest.get("backup_id"),
            "timestamp": manifest.get("timestamp"),
            "original_path": manifest.get("original_path"),
            "resolved_path": manifest.get("resolved_path"),
            "is_symlink": manifest.get("is_symlink"),
            "symlink_target": manifest.get("symlink_target"),
            "service": manifest.get("service"),
            "repair_ids": manifest.get("repair_ids") if isinstance(manifest.get("repair_ids"), list) else [],
            "verification": manifest.get("verification"),
            "manifest_path": str(manifest_path),
        }
        return self._sanitize_public(public)

    def read_backup_content(self, backup_id: str) -> bytes:
        manifest_path, manifest = self._load_manifest(backup_id)
        content_path = manifest_path.parent / "content"
        try:
            content = content_path.read_bytes()
        except OSError as exc:
            raise BackupError(f"Cannot read backup content: {exc}") from exc
        if hashlib.sha256(content).hexdigest() != manifest.get("sha256"):
            raise BackupError("Backup content hash does not match its manifest")
        return content

    def validate_backup_id(self, backup_id: str) -> str:
        if not self.ID_RE.fullmatch(backup_id):
            raise BackupError("Invalid backup identifier")
        return backup_id

    def _prepare_root(self) -> None:
        try:
            self.backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            if self.backup_dir.is_symlink() or not self.backup_dir.is_dir():
                raise BackupError(f"Unsafe backup directory: {self.backup_dir}")
            if os.name == "posix":
                self.backup_dir.chmod(0o700)
        except OSError as exc:
            raise BackupError(f"Cannot prepare backup directory {self.backup_dir}: {exc}") from exc

    def _load_manifest(self, backup_path: str) -> tuple[Path, dict]:
        candidate = Path(backup_path)
        if candidate.name != "manifest.json":
            candidate = self.backup_dir / self.validate_backup_id(candidate.name) / "manifest.json"
        try:
            root = self.backup_dir.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise BackupError("Backup path is outside the protected backup directory") from exc
        if resolved.name != "manifest.json" or not self.ID_RE.fullmatch(resolved.parent.name):
            raise BackupError("Invalid backup manifest path")
        try:
            if resolved.stat().st_size > 128 * 1024:
                raise BackupError("Backup manifest is too large")
            manifest = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(f"Cannot read backup manifest: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("backup_id") != resolved.parent.name:
            raise BackupError("Backup manifest identity is invalid")
        return resolved, manifest

    @classmethod
    def _sanitize_public(cls, value):
        if isinstance(value, dict):
            return {UI.clean(str(key)): cls._sanitize_public(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._sanitize_public(item) for item in value]
        if isinstance(value, str):
            return UI.clean(value)
        return value

    @staticmethod
    def _write_file(path: Path, data: bytes, mode: int) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(path, flags, mode)
        try:
            with os.fdopen(fd, "wb", closefd=True) as out:
                fd = -1
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            if os.name == "posix":
                path.chmod(mode)
        finally:
            if fd >= 0:
                os.close(fd)

    @staticmethod
    def _atomic_restore(path: Path, content: bytes, manifest: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = -1
        tmp: Path | None = None
        try:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".lixet-restore", dir=path.parent)
            tmp = Path(name)
            with os.fdopen(fd, "wb", closefd=True) as out:
                fd = -1
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
                if hasattr(os, "fchmod"):
                    os.fchmod(out.fileno(), int(manifest["mode"]))
                if hasattr(os, "fchown"):
                    try:
                        os.fchown(out.fileno(), int(manifest["uid"]), int(manifest["gid"]))
                    except PermissionError:
                        current = os.fstat(out.fileno())
                        if (getattr(current, "st_uid", 0), getattr(current, "st_gid", 0)) != (
                            int(manifest["uid"]),
                            int(manifest["gid"]),
                        ):
                            raise
            if not hasattr(os, "fchmod"):
                tmp.chmod(int(manifest["mode"]))
            os.replace(tmp, path)
            tmp = None
            os.utime(path, ns=(int(manifest["atime_ns"]), int(manifest["mtime_ns"])))
            if os.name == "posix":
                directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp and tmp.exists():
                tmp.unlink(missing_ok=True)

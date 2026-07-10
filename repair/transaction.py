# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Locked all-or-nothing repair transactions."""

from __future__ import annotations

import hashlib
import importlib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from backup.manager import BackupError, BackupManager, RollbackError
from core.models import VerificationResult, VerificationState
from repair.manager import RepairError, RepairManager
from repair.snapshot import FileSnapshot, SnapshotError, require_unchanged


class TransactionError(RuntimeError):
    """Raised when a repair transaction cannot complete safely."""


@dataclass(frozen=True)
class RepairPlan:
    path: str
    fixes: list[dict]
    snapshot: FileSnapshot
    service: str
    repair_ids: list[str]


@dataclass(frozen=True)
class TransactionResult:
    verification: VerificationResult
    backups: tuple[str, ...]


class RepairTransaction:
    _locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        backup_manager: BackupManager,
        repair_manager: RepairManager | None = None,
        lock_dir: str | Path = "/run/lock/lixet",
    ) -> None:
        self.backup_manager = backup_manager
        self.repair_manager = repair_manager or RepairManager()
        self.lock_dir = Path(lock_dir)

    def execute(
        self,
        plans: list[RepairPlan],
        verifier: Callable[[], VerificationResult],
    ) -> TransactionResult:
        if not plans:
            raise TransactionError("Repair transaction has no plans")
        lock = _TransactionLock(self._lock_path(plans), self._lock_for(plans))
        backups: list[tuple[RepairPlan, str]] = []
        changed: list[tuple[RepairPlan, str]] = []
        with lock:
            try:
                for plan in plans:
                    require_unchanged(plan.snapshot)
                    self.repair_manager.preview_fixes(plan.path, plan.fixes, plan.snapshot)
                for plan in plans:
                    backup = self.backup_manager.create_backup(
                        plan.path,
                        service=plan.service,
                        repair_ids=plan.repair_ids,
                        snapshot=plan.snapshot,
                    )
                    backups.append((plan, backup))
                for plan, backup in backups:
                    changed.append((plan, backup))
                    self.repair_manager.apply_fixes(plan.path, plan.fixes, plan.snapshot)
                result = verifier()
                for _plan, backup in backups:
                    self.backup_manager.update_verification(backup, result.state.value)
                if not result.successful:
                    raise TransactionError(result.message)
                return TransactionResult(result, tuple(item[1] for item in backups))
            except BaseException as exc:
                if changed:
                    self._rollback(changed, exc)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                if isinstance(exc, (TransactionError, RepairError, BackupError, SnapshotError)):
                    raise TransactionError(str(exc)) from exc
                raise

    def _rollback(self, changed: list[tuple[RepairPlan, str]], cause: BaseException) -> None:
        failures: list[str] = []
        for plan, backup in reversed(changed):
            try:
                self.backup_manager.restore_backup(backup, plan.path)
                self.backup_manager.update_verification(backup, "rolled back")
            except BackupError as exc:
                failures.append(f"{plan.path}: {exc}")
                try:
                    self.backup_manager.update_verification(backup, VerificationState.ROLLBACK_FAILED.value)
                except BackupError:
                    pass
        if failures:
            raise RollbackError("Rollback failed after transaction error: " + "; ".join(failures)) from cause

    def _lock_path(self, plans: list[RepairPlan]) -> Path:
        names = "\0".join(sorted(plan.snapshot.resolved_path for plan in plans))
        digest = hashlib.sha256(names.encode("utf-8")).hexdigest()[:24]
        return self.lock_dir / f"repair-{digest}.lock"

    @classmethod
    def _lock_for(cls, plans: list[RepairPlan]) -> threading.Lock:
        key = "\0".join(sorted(plan.snapshot.resolved_path for plan in plans))
        with cls._locks_guard:
            return cls._thread_locks.setdefault(key, threading.Lock())


class _TransactionLock:
    def __init__(self, path: Path, thread_lock: threading.Lock) -> None:
        self.path = path
        self.thread_lock = thread_lock
        self.handle: BinaryIO | None = None

    def __enter__(self):
        if not self.thread_lock.acquire(blocking=False):
            raise TransactionError("Another Lixet repair is already using this target")
        try:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            handle = self.path.open("a+b")
            self.handle = handle
            handle.seek(0)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            _lock_handle(handle)
            return self
        except BaseException as exc:
            if self.handle:
                self.handle.close()
                self.handle = None
            self.thread_lock.release()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, TransactionError):
                raise
            raise TransactionError("Another Lixet repair is already using this target") from exc

    def __exit__(self, *_args) -> None:
        try:
            if self.handle:
                _unlock_handle(self.handle)
                self.handle.close()
        finally:
            self.handle = None
            self.thread_lock.release()


def _lock_handle(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl" if os.name == "posix" else "msvcrt")
    if os.name == "posix":
        module.flock(handle.fileno(), module.LOCK_EX | module.LOCK_NB)
        return
    handle.seek(0)
    module.locking(handle.fileno(), module.LK_NBLCK, 1)


def _unlock_handle(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl" if os.name == "posix" else "msvcrt")
    if os.name == "posix":
        module.flock(handle.fileno(), module.LOCK_UN)
        return
    handle.seek(0)
    module.locking(handle.fileno(), module.LK_UNLCK, 1)

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Immutable filesystem snapshots used to detect concurrent changes."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


class SnapshotError(RuntimeError):
    """Raised when a target cannot be captured or changed safely."""


@dataclass(frozen=True)
class FileSnapshot:
    original_path: str
    resolved_path: str
    is_symlink: bool
    symlink_target: str | None
    link_device: int
    link_inode: int
    device: int
    inode: int
    size: int
    mtime_ns: int
    atime_ns: int
    sha256: str
    mode: int
    uid: int
    gid: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def capture_snapshot(file_path: str | Path) -> FileSnapshot:
    path = Path(file_path).absolute()
    try:
        link_stat = path.lstat()
    except OSError as exc:
        raise SnapshotError(f"Cannot inspect {path}: {exc}") from exc

    is_symlink = stat.S_ISLNK(link_stat.st_mode)
    symlink_target: str | None = None
    if is_symlink:
        try:
            symlink_target = os.readlink(path)
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SnapshotError(f"Broken, cyclic, or unreadable symlink {path}: {exc}") from exc
    else:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SnapshotError(f"Cannot resolve {path}: {exc}") from exc

    try:
        target_before = resolved.stat()
    except OSError as exc:
        raise SnapshotError(f"Cannot inspect resolved target {resolved}: {exc}") from exc
    if not stat.S_ISREG(target_before.st_mode):
        raise SnapshotError(f"Target is not a regular file: {resolved}")

    try:
        content = resolved.read_bytes()
        target_stat = resolved.stat()
        link_after = path.lstat()
    except OSError as exc:
        raise SnapshotError(f"Cannot read {resolved}: {exc}") from exc
    before_state = (target_before.st_dev, target_before.st_ino, target_before.st_size, target_before.st_mtime_ns)
    after_state = (target_stat.st_dev, target_stat.st_ino, target_stat.st_size, target_stat.st_mtime_ns)
    link_before_state = (link_stat.st_dev, link_stat.st_ino, link_stat.st_mode)
    link_after_state = (link_after.st_dev, link_after.st_ino, link_after.st_mode)
    if before_state != after_state or link_before_state != link_after_state or len(content) != target_stat.st_size:
        raise SnapshotError(f"File changed while it was being inspected: {path}")

    return FileSnapshot(
        original_path=str(path),
        resolved_path=str(resolved),
        is_symlink=is_symlink,
        symlink_target=symlink_target,
        link_device=link_stat.st_dev,
        link_inode=link_stat.st_ino,
        device=target_stat.st_dev,
        inode=target_stat.st_ino,
        size=target_stat.st_size,
        mtime_ns=target_stat.st_mtime_ns,
        atime_ns=target_stat.st_atime_ns,
        sha256=hashlib.sha256(content).hexdigest(),
        mode=stat.S_IMODE(target_stat.st_mode),
        uid=getattr(target_stat, "st_uid", 0),
        gid=getattr(target_stat, "st_gid", 0),
    )


def snapshot_matches(expected: FileSnapshot) -> bool:
    try:
        current = capture_snapshot(expected.original_path)
    except SnapshotError:
        return False
    return (
        current.original_path,
        current.resolved_path,
        current.is_symlink,
        current.symlink_target,
        current.link_device,
        current.link_inode,
        current.device,
        current.inode,
        current.size,
        current.mtime_ns,
        current.sha256,
        current.mode,
        current.uid,
        current.gid,
    ) == (
        expected.original_path,
        expected.resolved_path,
        expected.is_symlink,
        expected.symlink_target,
        expected.link_device,
        expected.link_inode,
        expected.device,
        expected.inode,
        expected.size,
        expected.mtime_ns,
        expected.sha256,
        expected.mode,
        expected.uid,
        expected.gid,
    )


def require_unchanged(expected: FileSnapshot) -> None:
    if not snapshot_matches(expected):
        raise SnapshotError(f"File changed after inspection: {expected.original_path}")

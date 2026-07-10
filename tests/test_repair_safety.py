# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Safety properties for snapshots, repairs, backups, and transactions."""

from __future__ import annotations

import codecs
import json
import os
import stat
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from backup.manager import BackupError, BackupManager, RollbackError
from core.models import VerificationResult, VerificationState
from repair.manager import RepairError, RepairManager
from repair.snapshot import SnapshotError, capture_snapshot
from repair.transaction import RepairPlan, RepairTransaction, TransactionError


def replace_fix(original: str, content: str) -> list[dict]:
    return [{"action": "replace", "line_number": 1, "content": content, "expected_original": original}]


class RepairManagerTests(unittest.TestCase):
    def test_line_repair_requires_expected_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_bytes(b"a=1\n")
            with self.assertRaises(RepairError):
                RepairManager.apply_fixes(str(path), [{"action": "replace", "line_number": 1, "content": "a=2"}])

    def test_preview_performs_zero_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_bytes(b"a=1\n")
            before = capture_snapshot(path)
            messages = RepairManager.preview_fixes(str(path), replace_fix("a=1\n", "a=2"), before)
            self.assertTrue(messages)
            after = capture_snapshot(path)
            self.assertEqual(
                (after.sha256, after.mtime_ns, after.inode), (before.sha256, before.mtime_ns, before.inode)
            )
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_changed_file_aborts_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_bytes(b"a=1\n")
            snapshot = capture_snapshot(path)
            path.write_bytes(b"a=external\n")
            with self.assertRaises((RepairError, SnapshotError)):
                RepairManager.apply_fixes(str(path), replace_fix("a=1\n", "a=2"), snapshot)
            self.assertEqual(path.read_bytes(), b"a=external\n")

    def test_mode_and_owner_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_bytes(b"a=1\n")
            path.chmod(0o640)
            before = capture_snapshot(path)
            RepairManager.apply_fixes(str(path), replace_fix("a=1\n", "a=2"), before)
            after = capture_snapshot(path)
            if os.name == "posix":
                self.assertEqual(after.mode, 0o640)
                self.assertEqual((after.uid, after.gid), (before.uid, before.gid))
            else:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR, before.mode & stat.S_IWUSR)

    def test_append_token_preserves_aliases_comment_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hosts"
            original = "127.0.0.1 host alias  # local alias\r\n"
            path.write_bytes(original.encode())
            RepairManager.apply_fixes(
                str(path),
                [{"action": "append_token", "line_number": 1, "token": "localhost", "expected_original": original}],
            )
            self.assertEqual(path.read_bytes(), b"127.0.0.1 host alias localhost # local alias\r\n")

    def test_symlink_survives_preview_failure_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            link = root / "link"
            target.write_bytes(b"a=1\n")
            try:
                link.symlink_to(target.name)
            except OSError:
                self._simulated_symlink_success(link, target)
                return
            snapshot = capture_snapshot(link)
            RepairManager.preview_fixes(str(link), replace_fix("a=1\n", "a=2"), snapshot)
            self.assertTrue(link.is_symlink())
            with self.assertRaises(RepairError):
                RepairManager.apply_fixes(str(link), replace_fix("wrong\n", "a=2"), snapshot)
            self.assertTrue(link.is_symlink())
            RepairManager.apply_fixes(str(link), replace_fix("a=1\n", "a=2"), snapshot)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"a=2\n")

    def _simulated_symlink_success(self, link: Path, target: Path) -> None:
        link.write_bytes(b"link-object\n")
        snapshot = replace(
            capture_snapshot(target), original_path=str(link.absolute()), is_symlink=True, symlink_target=target.name
        )
        original = Path.is_symlink
        with (
            mock.patch("repair.manager.require_unchanged"),
            mock.patch.object(
                Path, "is_symlink", lambda item: True if item.absolute() == link.absolute() else original(item)
            ),
        ):
            RepairManager.apply_fixes(str(link), replace_fix("a=1\n", "a=2"), snapshot)
        self.assertEqual(link.read_bytes(), b"link-object\n")
        self.assertEqual(target.read_bytes(), b"a=2\n")

    def test_broken_symlink_or_missing_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken"
            try:
                path.symlink_to("missing")
            except OSError:
                pass
            with self.assertRaises(SnapshotError):
                capture_snapshot(path)

    def test_all_text_actions_preserve_bom_comments_and_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            original = ["one # keep\r\n", "two\r\n", "three\r\n", "four\r\n", "five\r\n", "six"]
            path.write_bytes(codecs.BOM_UTF8 + "".join(original).encode())
            fixes = [
                {
                    "action": "replace_preserve_comment",
                    "line_number": 1,
                    "content": "changed",
                    "expected_original": original[0],
                },
                {"action": "comment_out", "line_number": 2, "expected_original": original[1]},
                {"action": "delete", "line_number": 3, "expected_original": original[2]},
                {
                    "action": "insert_before",
                    "line_number": 4,
                    "content": "before",
                    "expected_original": original[3],
                },
                {
                    "action": "insert_after",
                    "line_number": 5,
                    "content": "after",
                    "expected_original": original[4],
                },
                {
                    "action": "append_token",
                    "line_number": 6,
                    "token": "token",
                    "expected_original": original[5],
                },
                {"action": "append", "content": "tail\nsecond", "expected_eof": original[5]},
            ]
            self.assertTrue(RepairManager.apply_fixes(str(path), fixes))
            content = path.read_bytes()
            self.assertTrue(content.startswith(codecs.BOM_UTF8))
            self.assertIn(b"changed # keep\r\n", content)
            self.assertIn(b"# Lixet disabled: two\r\n", content)
            self.assertIn(b"before\r\nfour\r\n", content)
            self.assertIn(b"five\r\nafter\r\n", content)
            self.assertTrue(content.endswith(b"six token\r\ntail\r\nsecond\r\n"))

    def test_invalid_repair_shapes_are_rejected(self) -> None:
        cases = [
            [{"action": "unknown"}],
            [{"action": "delete", "line_number": "bad", "expected_original": "x\n"}],
            [{"action": "delete", "line_number": 1}],
            [
                {"action": "delete", "line_number": 1, "expected_original": "x\n"},
                {"action": "comment_out", "line_number": 1, "expected_original": "x\n"},
            ],
            [{"action": "replace", "line_number": 1, "expected_original": "x\n"}],
            [{"action": "append", "content": "x"}],
            [{"action": "append_token", "line_number": 1, "token": " ", "expected_original": "x\n"}],
        ]
        for fixes in cases:
            with self.subTest(fixes=fixes), self.assertRaises(RepairError):
                RepairManager._normalize_fixes(fixes)

    def test_repair_rejects_wrong_snapshot_bounds_and_changed_eof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            other = root / "other"
            path.write_bytes(b"one\n")
            other.write_bytes(b"two\n")
            with self.assertRaises(RepairError):
                RepairManager.preview_fixes(str(path), replace_fix("one\n", "new"), capture_snapshot(other))
            with self.assertRaises(RepairError):
                RepairManager.preview_fixes(
                    str(path),
                    [{"action": "delete", "line_number": 2, "expected_original": "missing\n"}],
                )
            with self.assertRaises(RepairError):
                RepairManager.preview_fixes(str(path), [{"action": "append", "content": "x", "expected_eof": "old"}])

    def test_invalid_utf8_is_reported_as_repair_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_bytes(b"\xff\xfe")
            with self.assertRaises(RepairError):
                RepairManager.apply_fixes(str(path), [])


class BackupManagerTests(unittest.TestCase):
    def test_backup_bundle_has_manifest_and_is_not_adjacent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "nginx" / "conf.d"
            config_dir.mkdir(parents=True)
            config = config_dir / "site.conf"
            config.write_bytes(b"server {}\n")
            backup_root = root / "backups"
            manager = BackupManager(backup_root)
            manifest_path = Path(manager.create_backup(str(config), "nginx", ["repair-id"]))
            self.assertTrue(manifest_path.is_file())
            self.assertNotEqual(manifest_path.parent.parent, config.parent)
            self.assertFalse(any(config_dir.glob("*.bak")))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for field in (
                "backup_id",
                "timestamp",
                "original_path",
                "resolved_path",
                "is_symlink",
                "sha256",
                "uid",
                "gid",
                "mode",
                "service",
                "repair_ids",
                "verification",
            ):
                self.assertIn(field, manifest)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backup_root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)

    def test_restore_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = BackupManager(Path(tmp) / "backups")
            with self.assertRaises(BackupError):
                manager.restore_backup("../manifest.json")

    def test_restore_verifies_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            path.write_bytes(b"before\n")
            manager = BackupManager(root / "backups")
            manifest = Path(manager.create_backup(str(path)))
            (manifest.parent / "content").write_bytes(b"tampered\n")
            with self.assertRaises(RollbackError):
                manager.restore_backup(str(manifest), str(path))


class TransactionTests(unittest.TestCase):
    def test_multi_file_interrupt_restores_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / "one", root / "two"]
            for path in paths:
                path.write_bytes(b"old\n")
            plans = [
                RepairPlan(str(path), replace_fix("old\n", "new"), capture_snapshot(path), "test", [path.name])
                for path in paths
            ]

            class InterruptingRepair(RepairManager):
                calls = 0

                @classmethod
                def apply_fixes(cls, file_path, fixes, snapshot=None):
                    result = super().apply_fixes(file_path, fixes, snapshot)
                    cls.calls += 1
                    if cls.calls == 2:
                        raise KeyboardInterrupt
                    return result

            transaction = RepairTransaction(BackupManager(root / "backups"), InterruptingRepair(), root / "locks")
            with self.assertRaises(KeyboardInterrupt):
                transaction.execute(plans, lambda: VerificationResult(VerificationState.INTERNALLY_VERIFIED, "ok"))
            self.assertEqual([path.read_bytes() for path in paths], [b"old\n", b"old\n"])

    def test_verification_failure_rolls_back_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            link = root / "link"
            target.write_bytes(b"old\n")
            try:
                link.symlink_to(target.name)
            except OSError:
                self._normal_rollback_fallback(root, target)
                return
            plan = RepairPlan(str(link), replace_fix("old\n", "new"), capture_snapshot(link), "test", ["id"])
            transaction = RepairTransaction(BackupManager(root / "backups"), lock_dir=root / "locks")
            with self.assertRaises(TransactionError):
                transaction.execute([plan], lambda: VerificationResult(VerificationState.FAILED, "injected"))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"old\n")

    def _normal_rollback_fallback(self, root: Path, target: Path) -> None:
        plan = RepairPlan(str(target), replace_fix("old\n", "new"), capture_snapshot(target), "test", ["id"])
        transaction = RepairTransaction(BackupManager(root / "backups"), lock_dir=root / "locks")
        with self.assertRaises(TransactionError):
            transaction.execute([plan], lambda: VerificationResult(VerificationState.FAILED, "injected"))
        self.assertEqual(target.read_bytes(), b"old\n")

    def test_rollback_failure_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            path.write_bytes(b"old\n")

            class BrokenRestore(BackupManager):
                def restore_backup(self, backup_path, file_path=None):
                    raise BackupError("injected rollback failure")

            plan = RepairPlan(str(path), replace_fix("old\n", "new"), capture_snapshot(path), "test", ["id"])
            transaction = RepairTransaction(BrokenRestore(root / "backups"), lock_dir=root / "locks")
            with self.assertRaises(RollbackError):
                transaction.execute([plan], lambda: VerificationResult(VerificationState.FAILED, "injected"))

    def test_concurrent_transaction_is_rejected_without_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            path.write_bytes(b"old\n")
            snapshot = capture_snapshot(path)
            plan = RepairPlan(str(path), replace_fix("old\n", "new"), snapshot, "test", ["id"])
            entered = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []

            class BlockingRepair(RepairManager):
                @classmethod
                def apply_fixes(cls, file_path, fixes, snapshot=None):
                    entered.set()
                    release.wait(5)
                    return super().apply_fixes(file_path, fixes, snapshot)

            first = RepairTransaction(BackupManager(root / "backups-one"), BlockingRepair(), root / "locks")
            second = RepairTransaction(BackupManager(root / "backups-two"), lock_dir=root / "locks")

            def run_first() -> None:
                try:
                    first.execute([plan], lambda: VerificationResult(VerificationState.INTERNALLY_VERIFIED, "ok"))
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=run_first)
            thread.start()
            self.assertTrue(entered.wait(5))
            with self.assertRaises(TransactionError):
                second.execute([plan], lambda: VerificationResult(VerificationState.INTERNALLY_VERIFIED, "ok"))
            release.set()
            thread.join(5)
            self.assertFalse(errors)
            self.assertEqual(path.read_bytes(), b"new\n")


if __name__ == "__main__":
    unittest.main()

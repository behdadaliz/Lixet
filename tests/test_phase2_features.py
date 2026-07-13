# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Phase 2 user-facing features."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backup.manager import BackupManager
from cli.parser import parse_and_execute
from core.engine import LixetEngine
from core.models import ExitCode
from services.fail2ban_service import Fail2banService
from tests.helpers import FakeRunner
from utils.ui import UI
from validators.fail2ban_validator import Fail2banValidator


class Phase2ScanTests(unittest.TestCase):
    def _runner(self) -> FakeRunner:
        return FakeRunner(
            {
                ("ip", "route"): {"returncode": 0, "evidence": "default via 10.0.0.1", "command": "ip route"},
                ("ip", "addr"): {"returncode": 0, "evidence": "inet 10.0.0.2/24", "command": "ip addr"},
                ("ip", "link"): {"returncode": 0, "evidence": "2: eth0: <BROADCAST,UP>", "command": "ip link"},
            }
        )

    def test_direct_known_path_scan_and_aliases_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "etc" / "hosts"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"127.0.0.1 localhost\n::1 localhost\n")
            engine = LixetEngine(no_color=True, runner=self._runner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine.scan(str(path)), ExitCode.OK)
            self.assertIn("Configuration Detected", out.getvalue())
            alias_engine = LixetEngine(config_path=str(path), no_color=True, runner=self._runner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(alias_engine.scan("hosts"), ExitCode.OK)

    def test_type_override_conflicts_and_unknown_paths_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom-nginx.conf"
            path.write_bytes(b"events {}\n")
            engine = LixetEngine(target_type="nginx", no_color=True, runner=FakeRunner())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(engine.scan(str(path)), ExitCode.ISSUES)
            conflict = LixetEngine(config_path="/other", no_color=True, runner=FakeRunner())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(conflict.scan(str(path)), ExitCode.USAGE)
            missing = LixetEngine(no_color=True, runner=FakeRunner())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(missing.scan(str(Path(tmp) / "missing.conf")), ExitCode.USAGE)
            typed_service = LixetEngine(target_type="nginx", no_color=True, runner=FakeRunner())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(typed_service.scan("ssh"), ExitCode.USAGE)

    def test_noninteractive_and_interactive_detector_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ambiguous.txt"
            path.write_bytes(b"events {\nExecStart=/bin/true\n")
            noninteractive = LixetEngine(no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(noninteractive.scan(str(path)), ExitCode.USAGE)
            self.assertIn("--type <service>", out.getvalue())

            interactive = LixetEngine(
                no_color=True,
                runner=FakeRunner(),
                ui=UI(no_color=True, stdin=io.StringIO("q\n"), force_interactive=True),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(interactive.scan(str(path)), ExitCode.USAGE)

    def test_binary_empty_and_unreadable_detection_errors_do_not_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "binary"
            empty = root / "empty"
            binary.write_bytes(b"\x00\x01")
            empty.write_bytes(b"")
            engine = LixetEngine(no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(engine.scan(str(binary)), ExitCode.USAGE)
                self.assertEqual(engine.scan(str(empty)), ExitCode.USAGE)
            with mock.patch("core.detector.TargetDetector._read_prefix", side_effect=PermissionError("denied")):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(engine.scan(str(empty)), ExitCode.INSPECTION_FAILED)
            self.assertNotIn("Traceback", out.getvalue())


class Phase2DiffAndDoctorTests(unittest.TestCase):
    def test_dry_run_shows_unified_diff_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            before = b"127.0.0.1 myhost\n::1 localhost\n"
            hosts.write_bytes(before)
            engine = LixetEngine(
                dry_run=True,
                config_path=str(hosts),
                no_color=True,
                backup_dir=root / "backups",
                runner=FakeRunner(),
                ui=UI(no_color=True, stdin=io.StringIO("")),
            )
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine.scan_service("networking"), ExitCode.ISSUES)
            text = out.getvalue()
            self.assertIn("@@", text)
            self.assertIn("-127.0.0.1 myhost", text)
            self.assertIn("+127.0.0.1 myhost localhost", text)
            self.assertEqual(hosts.read_bytes(), before)
            self.assertFalse((root / "backups").exists())

    def test_preview_refuses_diff_when_file_changed_after_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 myhost\n::1 localhost\n")
            engine = LixetEngine(
                dry_run=True,
                config_path=str(hosts),
                no_color=True,
                backup_dir=root / "backups",
                runner=FakeRunner(),
                ui=UI(no_color=True, stdin=io.StringIO("")),
            )
            result = engine._inspect("networking", custom_path=str(hosts))
            hosts.write_bytes(b"changed\n")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine._preview([("networking", result.issues[0])]), ExitCode.REPAIR_FAILED)
            self.assertIn("Cannot preview repairs", out.getvalue())
            self.assertEqual(hosts.read_bytes(), b"changed\n")
            self.assertFalse((root / "backups").exists())

    def test_doctor_selection_range_rescan_quit_and_guarded_skip(self) -> None:
        item1 = {"id": "1", "code": "A", "repairable": True, "repair_level": "safe", "fixes": [{"action": "append"}]}
        item2 = {"id": "2", "code": "B", "repairable": False, "repair_level": "unsafe", "fixes": []}
        engine = LixetEngine(no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("1-2\ny\n"), force_interactive=True))
        with mock.patch.object(engine, "_execute_repairs", return_value=ExitCode.ISSUES) as execute:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine._offer_repairs([("ssh", item1), ("ssh", item2)], doctor=True), ExitCode.OK)
        execute.assert_called_once()
        self.assertIn("Skipped report-only issue", out.getvalue())


class Phase2BackupRestoreTests(unittest.TestCase):
    def test_backups_list_skips_corrupt_and_restore_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "hosts"
            target.write_bytes(b"old\n")
            manager = BackupManager(root / "backups")
            manifest = manager.create_backup(str(target), service="networking", repair_ids=["x"])
            backup_id = Path(manifest).parent.name
            target.write_bytes(b"new\n")
            corrupt = manager.backup_dir / "20260712T120000Z-1111111111111111"
            corrupt.mkdir()
            (corrupt / "manifest.json").write_text("{bad", encoding="utf-8")
            engine = LixetEngine(dry_run=True, no_color=True, backup_dir=manager.backup_dir, ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine.show_backups(), ExitCode.OK)
                self.assertEqual(engine.restore_backup(backup_id), ExitCode.ISSUES)
            text = out.getvalue()
            self.assertIn(backup_id, text)
            self.assertIn("Skipped corrupt backup", text)
            self.assertIn("-new", text)
            self.assertIn("+old", text)
            self.assertEqual(target.read_bytes(), b"new\n")

    def test_successful_restore_requires_restore_and_creates_pre_restore_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "hosts"
            target.write_bytes(b"old\n")
            manager = BackupManager(root / "backups")
            manifest = manager.create_backup(str(target), service="networking", repair_ids=["x"])
            backup_id = Path(manifest).parent.name
            target.write_bytes(b"new\n")
            engine = LixetEngine(
                no_color=True,
                backup_dir=manager.backup_dir,
                ui=UI(no_color=True, stdin=io.StringIO("RESTORE\n"), force_interactive=True),
            )
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(engine.restore_backup(backup_id), ExitCode.OK)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertIn("Pre-restore backup", out.getvalue())
            self.assertEqual(len(list(manager.backup_dir.glob("*/manifest.json"))), 2)

    def test_restore_cancel_and_noninteractive_refuse_without_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "hosts"
            target.write_bytes(b"old\n")
            manager = BackupManager(root / "backups")
            backup_id = Path(manager.create_backup(str(target))).parent.name
            target.write_bytes(b"new\n")
            cancel = LixetEngine(no_color=True, backup_dir=manager.backup_dir, ui=UI(no_color=True, stdin=io.StringIO("yes\n"), force_interactive=True))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cancel.restore_backup(backup_id), ExitCode.ISSUES)
            self.assertEqual(target.read_bytes(), b"new\n")
            noninteractive = LixetEngine(no_color=True, backup_dir=manager.backup_dir, ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(noninteractive.restore_backup(backup_id), ExitCode.REPAIR_FAILED)


class Phase2Fail2banTests(unittest.TestCase):
    def test_fail2ban_inspects_paths_includes_and_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "etc" / "fail2ban"
            root.mkdir(parents=True)
            (root / "jail.local").write_bytes(b"[INCLUDES]\nbefore = extra.conf\n[sshd]\nenabled = true\n")
            (root / "extra.conf").write_bytes(b"[INCLUDES]\nbefore = jail.local\n")
            runner = FakeRunner()
            data = Fail2banService(str(root), runner).inspect()
            self.assertTrue(any("cycle" in item.lower() for item in data["include_errors"]))
            self.assertIn(("fail2ban-client", "-t", "-c", str(root)), runner.calls)
            self.assertTrue(any(Path(item["file_path"]).name == "jail.local" for item in data["files"]))

    def test_fail2ban_validator_report_only_and_guarded_override(self) -> None:
        path = "/etc/fail2ban/jail.local"
        rows = [
            {"file_path": path, "line_number": 1, "raw_line": "[sshd]\n", "text": "[sshd]", "is_active": True},
            {"file_path": path, "line_number": 2, "raw_line": "enabled = maybe\n", "text": "enabled = maybe", "is_active": True},
            {"file_path": path, "line_number": 3, "raw_line": "maxretry = zero\n", "text": "maxretry = zero", "is_active": True},
        ]
        data = {
            "config_dir": "/etc/fail2ban",
            "files": [{"file_path": path, "lines": rows}],
            "include_errors": ["missing include"],
            "config_test": {"returncode": 1, "evidence": f"{path}:2: bad value", "command": "fail2ban-client -t"},
            "runtime_status": {"returncode": 1, "evidence": "socket missing", "command": "fail2ban-client status"},
        }
        issues = Fail2banValidator("/etc/fail2ban").run_rules(data)
        codes = {item["code"] for item in issues}
        self.assertIn("FAIL2BAN_INCLUDE_MISSING", codes)
        self.assertIn("FAIL2BAN_INVALID_BOOLEAN", codes)
        self.assertIn("FAIL2BAN_INVALID_POSITIVE_INTEGER", codes)
        guarded = next(item for item in issues if item["code"] == "FAIL2BAN_CONFIG_TEST_FAILED")
        self.assertEqual(guarded["repair_level"], "guarded")
        self.assertTrue(guarded["repairable"])

    def test_fail2ban_registry_alias_and_directory_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "etc" / "fail2ban"
            root.mkdir(parents=True)
            (root / "jail.local").write_bytes(b"[sshd]\nenabled = false\n")
            engine = LixetEngine(config_path=str(root), no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            direct = LixetEngine(no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIn(engine.scan("f2b"), {ExitCode.ISSUES, ExitCode.OK})
                self.assertIn(direct.scan(str(root)), {ExitCode.ISSUES, ExitCode.OK})


class Phase2HelpVersionTests(unittest.TestCase):
    def test_help_services_and_version(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(parse_and_execute(["--no-color"]), 0)
        text = out.getvalue()
        self.assertIn("backups", text)
        self.assertIn("restore", text)
        self.assertIn("fail2ban", text)
        with contextlib.redirect_stdout(io.StringIO()) as services:
            self.assertEqual(parse_and_execute(["--no-color", "services"]), 0)
        self.assertIn("/etc/fail2ban", services.getvalue())


if __name__ == "__main__":
    unittest.main()

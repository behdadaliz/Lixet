# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Phase 1 internal foundations for v0.3.0-beta features."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backup.manager import BackupError, BackupManager
from cli.parser import parse_and_execute
from core.detector import DetectionStatus, TargetDetector
from core.engine import LixetEngine
from core.models import ExitCode
from core.registry import aliases, aliases_for, iter_services, service_help, service_names, valid_target_types
from repair.manager import RepairManager
from tests.helpers import FakeRunner
from utils.diff import DiffFile, render_colored, render_diff, render_plain, repaired_bytes, unified_diff_lines
from utils.selection import SelectionAction, parse_selection
from utils.ui import UI


class RegistryTests(unittest.TestCase):
    EXPECTED = ("ssh", "nginx", "ufw", "dns", "networking", "fail2ban", "systemd", "sudoers", "fstab", "sysctl")

    def test_every_current_service_is_registered_in_stable_order(self) -> None:
        self.assertEqual(service_names(), self.EXPECTED)
        self.assertEqual([item[0] for item in service_help()], list(self.EXPECTED))

    def test_aliases_are_unique_and_target_known_services(self) -> None:
        found = aliases()
        self.assertEqual(found["sshd"], "ssh")
        self.assertEqual(found["openssh"], "ssh")
        self.assertEqual(found["hosts"], "networking")
        self.assertEqual(found["network"], "networking")
        self.assertEqual(found["firewall"], "ufw")
        self.assertEqual(found["f2b"], "fail2ban")
        self.assertEqual(found["fail2ban-client"], "fail2ban")
        self.assertEqual(len(found), len(set(found)))
        self.assertTrue(set(found.values()).issubset(set(service_names())))
        self.assertEqual(aliases_for("ssh"), ("sshd", "openssh"))

    def test_canonical_names_defaults_and_target_types_are_valid(self) -> None:
        names = [item.name for item in iter_services()]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(valid_target_types(), ("file", "directory"))
        for spec in iter_services():
            self.assertTrue(spec.default_path.startswith("/"))
            self.assertIn(spec.default_path, spec.known_paths)
            self.assertTrue(spec.accepted_target_types)

    def test_engine_and_parser_use_registry_metadata(self) -> None:
        engine = LixetEngine(no_color=True, runner=FakeRunner())
        self.assertEqual(tuple(engine.supported_services), service_names())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(parse_and_execute(["--no-color"]), 0)
        self.assertIn(", ".join(service_names()), output.getvalue())

    def test_scan_doctor_and_services_keep_existing_registry_order(self) -> None:
        engine = LixetEngine(no_color=True, runner=FakeRunner())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = engine.show_services()
        self.assertEqual(code, ExitCode.OK)
        rendered = output.getvalue()
        self.assertLess(rendered.index("ssh"), rendered.index("nginx"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_text("127.0.0.1 localhost\n::1 localhost\n", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("ip", "route"): {"returncode": 0, "evidence": "default via 10.0.0.1", "command": "ip route"},
                    ("ip", "addr"): {"returncode": 0, "evidence": "inet 10.0.0.2/24", "command": "ip addr"},
                    ("ip", "link"): {"returncode": 0, "evidence": "2: eth0: <BROADCAST,UP>", "command": "ip link"},
                }
            )
            scan = LixetEngine(config_path=str(hosts), no_color=True, runner=runner)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scan.scan_service("hosts"), ExitCode.OK)


class DetectorTests(unittest.TestCase):
    def _write(self, relative: str, data: bytes = b"") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.detector = TargetDetector(max_read=32)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exact_path_detection_is_strongest(self) -> None:
        path = self._write("etc/ssh/sshd_config", b"")
        result = self.detector.detect(path)
        self.assertEqual(result.status, DetectionStatus.MATCH)
        self.assertEqual(result.best.service, "ssh")
        self.assertEqual(result.best.evidence[0].kind, "exact_path")

    def test_filename_detection_and_clear_match(self) -> None:
        path = self._write("work/nginx.conf", b"events {}\nhttp {}\n")
        result = self.detector.detect(path)
        self.assertEqual(result.status, DetectionStatus.MATCH)
        self.assertEqual(result.best.service, "nginx")

    def test_parent_directory_detection(self) -> None:
        path = self._write("etc/sysctl.d/90-local.conf", b"vm.swappiness=10\n")
        result = self.detector.detect(path)
        self.assertEqual(result.status, DetectionStatus.MATCH)
        self.assertEqual(result.best.service, "sysctl")

    def test_content_only_detection_is_not_auto_selected(self) -> None:
        path = self._write("random.conf", b"PermitRootLogin no\n")
        result = self.detector.detect(path)
        self.assertEqual(result.status, DetectionStatus.UNKNOWN)
        self.assertEqual(result.candidates[0].service, "ssh")

    def test_ambiguous_content_match_keeps_candidates(self) -> None:
        path = self._write("random.txt", b"events {\nExecStart=/bin/true\n")
        result = self.detector.detect(path)
        self.assertEqual(result.status, DetectionStatus.AMBIGUOUS)
        self.assertGreaterEqual(len(result.candidates), 2)

    def test_unknown_empty_binary_and_invalid_utf8_files_are_safe(self) -> None:
        empty = self._write("empty.txt", b"")
        binary = self._write("binary.conf", b"\x00\x01\x02")
        invalid = self._write("invalid.conf", b"\xffPermitRootLogin no\n")
        self.assertEqual(self.detector.detect(empty).status, DetectionStatus.UNKNOWN)
        binary_result = self.detector.detect(binary)
        self.assertEqual(binary_result.status, DetectionStatus.UNKNOWN)
        self.assertTrue(binary_result.binary)
        self.assertEqual(self.detector.detect(invalid).status, DetectionStatus.UNKNOWN)

    def test_supported_directory_and_stable_ordering(self) -> None:
        directory = self.root / "etc/systemd/system"
        directory.mkdir(parents=True)
        result = self.detector.detect(directory)
        self.assertEqual(result.status, DetectionStatus.MATCH)
        self.assertEqual(result.best.service, "systemd")
        self.assertEqual([item.service for item in result.candidates], sorted([item.service for item in result.candidates], key=lambda name: result.candidates[[c.service for c in result.candidates].index(name)].score, reverse=True))

    def test_safe_symlink_and_broken_symlink(self) -> None:
        target = self._write("etc/hosts", b"127.0.0.1 localhost\n")
        link = self.root / "hosts-link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are unavailable on this platform")
        self.assertEqual(self.detector.detect(link).status, DetectionStatus.MATCH)
        broken = self.root / "broken"
        broken.symlink_to(self.root / "missing")
        self.assertEqual(self.detector.detect(broken).status, DetectionStatus.ERROR)

    def test_bounded_reading_and_read_error(self) -> None:
        path = self._write("sshd_config", b"PermitRootLogin no\n" + b"x" * 200)
        result = self.detector.detect(path)
        self.assertTrue(result.truncated)
        with mock.patch.object(TargetDetector, "_read_prefix", side_effect=PermissionError("denied")):
            denied = TargetDetector().detect(path)
        self.assertEqual(denied.status, DetectionStatus.ERROR)
        self.assertIn("denied", denied.message)


class DiffTests(unittest.TestCase):
    def _fix(self, original: str, fixes: list[dict]) -> str:
        return repaired_bytes(original.encode("utf-8"), fixes).decode("utf-8")

    def test_repair_actions_use_repair_manager_logic(self) -> None:
        original = "one\nold value # keep\nthree\n"
        fixes = [
            {"action": "replace_preserve_comment", "line_number": 2, "content": "new value", "expected_original": "old value # keep\n"},
            {"action": "insert_before", "line_number": 1, "content": "zero", "expected_original": "one\n"},
            {"action": "insert_after", "line_number": 3, "content": "four", "expected_original": "three\n"},
            {"action": "append", "content": "five", "expected_eof": "three\n"},
        ]
        self.assertEqual(self._fix(original, fixes), "zero\none\nnew value # keep\nthree\nfour\nfive\n")

    def test_delete_comment_out_append_token_and_multiple_changes(self) -> None:
        original = "host alias # c\nbad\nremove\n"
        fixes = [
            {"action": "append_token", "line_number": 1, "token": "localhost", "expected_original": "host alias # c\n"},
            {"action": "comment_out_with_reason", "line_number": 2, "reason": "disabled", "expected_original": "bad\n"},
            {"action": "delete", "line_number": 3, "expected_original": "remove\n"},
        ]
        self.assertEqual(self._fix(original, fixes), "host alias localhost # c\n# disabled: bad\n")

    def test_unified_diff_plain_colored_and_multiple_files(self) -> None:
        files = [DiffFile("a.conf", "a\n", "b\n"), DiffFile("b.conf", "x\n", "x\ny\n")]
        plain = render_plain(files)
        self.assertIn("--- a/a.conf", plain)
        self.assertIn("+b", plain)
        ui = UI(no_color=False)
        ui.color = True
        colored = render_colored(files, ui)
        self.assertIn(UI.GREEN, colored)
        no_color = render_diff(files, UI(no_color=True))
        self.assertNotIn("\033[", no_color)

    def test_lf_crlf_bom_missing_final_newline_and_sanitizing(self) -> None:
        bom = b"\xef\xbb\xbfkey=old\r\n"
        after = repaired_bytes(bom, [{"action": "replace", "line_number": 1, "content": "key=new", "expected_original": "key=old\r\n"}])
        self.assertTrue(after.startswith(b"\xef\xbb\xbfkey=new\r\n"))
        diff = unified_diff_lines("bad\x1b[31m.conf", "a", "a\nb\n")
        self.assertTrue(any("bad" in line and "\x1b" not in line for line in diff))

    def test_preview_diff_performs_zero_writes_and_zero_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "hosts"
            path.write_bytes(b"127.0.0.1 host\n")
            before = path.read_bytes()
            after = repaired_bytes(
                before,
                [{"action": "append_token", "line_number": 1, "token": "localhost", "expected_original": "127.0.0.1 host\n"}],
            )
            self.assertIn("+127.0.0.1 host localhost", render_plain([DiffFile(str(path), before, after)]))
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((root / "backups").exists())


class SelectionParserTests(unittest.TestCase):
    def test_basic_actions(self) -> None:
        self.assertEqual(parse_selection("", 3).action, SelectionAction.EMPTY)
        self.assertEqual(parse_selection("a", 3).action, SelectionAction.ALL)
        self.assertEqual(parse_selection("r", 3).action, SelectionAction.RESCAN)
        self.assertEqual(parse_selection("q", 3).action, SelectionAction.QUIT)

    def test_numbers_ranges_deduplicate_and_preserve_order(self) -> None:
        self.assertEqual(parse_selection("1, 3-5, 3, 8", 8).indexes, (1, 3, 4, 5, 8))

    def test_invalid_inputs_are_friendly(self) -> None:
        for text in ("0", "-1", "4-1", "1,,2", "x", "1-2-3", "9"):
            result = parse_selection(text, 5)
            self.assertEqual(result.action, SelectionAction.INVALID)
            self.assertTrue(result.error)


class BackupQueryTests(unittest.TestCase):
    def _backup(self, manager: BackupManager, path: Path, content: bytes = b"value\n") -> str:
        path.write_bytes(content)
        return manager.create_backup(str(path), service="networking", repair_ids=["issue-1"])

    def test_no_one_and_several_backups_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = BackupManager(Path(tmp) / "backups")
            self.assertEqual(manager.list_backups(), [])
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            with mock.patch("backup.manager.secrets.token_hex", side_effect=["0000000000000000", "ffffffffffffffff"]):
                self._backup(manager, first, b"1\n")
                self._backup(manager, second, b"2\n")
            items = manager.list_backups()
            self.assertEqual(len(items), 2)
            self.assertGreater(items[0].backup_id, items[1].backup_id)
            self.assertEqual(manager.read_backup_content(items[0].backup_id), b"2\n")

    def test_corrupt_malformed_oversized_and_missing_content_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = BackupManager(root / "backups")
            bundle = manager.backup_dir / "20260712T120000Z-0123456789abcdef"
            bundle.mkdir(parents=True)
            (bundle / "manifest.json").write_text("{bad", encoding="utf-8")
            self.assertTrue(manager.list_backups()[0].error)
            (bundle / "manifest.json").write_text("x" * (129 * 1024), encoding="utf-8")
            self.assertTrue(manager.list_backups()[0].error)
            target = root / "target"
            manifest_path = self._backup(manager, target)
            Path(manifest_path).with_name("content").unlink()
            with self.assertRaises(BackupError):
                manager.read_backup_content(Path(manifest_path).parent.name)

    def test_invalid_id_traversal_hash_mismatch_and_sanitized_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = BackupManager(root / "backups")
            target = root / "target"
            manifest_path = Path(self._backup(manager, target))
            backup_id = manifest_path.parent.name
            with self.assertRaises(BackupError):
                manager.validate_backup_id("../x")
            with self.assertRaises(BackupError):
                manager.load_public_metadata("../x")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["service"] = "\x1b[31mnetworking"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(manager.load_public_metadata(backup_id)["service"], "networking")
            (manifest_path.parent / "content").write_bytes(b"changed")
            with self.assertRaises(BackupError):
                manager.read_backup_content(backup_id)


if __name__ == "__main__":
    unittest.main()

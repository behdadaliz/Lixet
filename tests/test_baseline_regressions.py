# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Isolated regressions for the release-blocking baseline failures."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from backup.manager import BackupManager
from cli.parser import parse_and_execute
from core.engine import LixetEngine
from core.install_transaction import InstallError, InstallTransaction
from core.updater import LixetUpdater
from core.version import version_key
from repair.manager import RepairError, RepairManager
from repair.snapshot import capture_snapshot
from validators.dns_validator import DNSValidator
from validators.fstab_validator import FstabValidator
from validators.helpers import run_command
from validators.nginx_validator import NginxValidator
from validators.ssh_validator import SSHValidator
from validators.sysctl_validator import SysctlValidator
from validators.systemd_validator import SystemdValidator
from validators.ufw_validator import UFWValidator


def row(number: int, text: str) -> dict:
    raw = text if text.endswith("\n") else text + "\n"
    clean = raw.strip()
    return {
        "line_number": number,
        "raw_line": raw,
        "text": clean,
        "is_active": bool(clean and not clean.startswith("#")),
    }


class ReleaseBlockerBaselineTests(unittest.TestCase):
    def test_repair_keeps_symlink_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.conf"
            link = root / "link.conf"
            target.write_bytes(b"value=bad\n")
            try:
                link.symlink_to(target.name)
            except OSError:
                link.write_text("simulated-link-object\n", encoding="utf-8")
                snapshot = replace(
                    capture_snapshot(target),
                    original_path=str(link.absolute()),
                    is_symlink=True,
                    symlink_target=target.name,
                )
                original_is_symlink = Path.is_symlink
                with (
                    mock.patch("repair.manager.require_unchanged"),
                    mock.patch.object(
                        Path,
                        "is_symlink",
                        lambda item: True if item.absolute() == link.absolute() else original_is_symlink(item),
                    ),
                ):
                    RepairManager.apply_fixes(
                        str(link),
                        [
                            {
                                "action": "replace",
                                "line_number": 1,
                                "content": "value=good",
                                "expected_original": "value=bad\n",
                            }
                        ],
                        snapshot,
                    )
                self.assertEqual(link.read_text(encoding="utf-8"), "simulated-link-object\n")
                self.assertEqual(target.read_text(encoding="utf-8"), "value=good\n")
                return

            RepairManager.apply_fixes(
                str(link),
                [{"action": "replace", "line_number": 1, "content": "value=good", "expected_original": "value=bad\n"}],
            )

            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "value=good\n")

    def test_doctor_rejects_custom_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "sshd_config"
            config.write_text("Port 22\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                parse_and_execute(["doctor", "--config", str(config), "--dry-run", "--no-color"])
        self.assertEqual(raised.exception.code, 2)

    def test_installer_staging_failure_preserves_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "lixet"
            command = root / "bin" / "lixet"
            installed.mkdir()
            sentinel = installed / "sentinel"
            sentinel.write_text("old", encoding="utf-8")

            transaction = InstallTransaction(Path(__file__).resolve().parents[1], installed, command, force=True)
            with (
                mock.patch.object(
                    InstallTransaction, "_copy_tree", side_effect=RuntimeError("injected staging failure")
                ),
                self.assertRaises(InstallError),
            ):
                transaction.install()

            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "old")

    def test_sysctl_effective_override_is_report_only(self) -> None:
        data = {
            "files": [
                {"file_path": "/tmp/10-base.conf", "lines": [row(1, "net.ipv4.ip_forward = 0")]},
                {"file_path": "/tmp/90-local.conf", "lines": [row(1, "net.ipv4.ip_forward = 1")]},
            ]
        }
        issues = SysctlValidator("/tmp/sysctl.conf").run_rules(data)
        duplicate = next(item for item in issues if item["code"] == "SYSCTL_EFFECTIVE_OVERRIDE")
        self.assertFalse(duplicate["repairable"])

    def test_ufw_later_assignment_is_report_only(self) -> None:
        data = {
            "file_path": "/tmp/ufw.conf",
            "lines": [row(1, "ENABLED=no"), row(2, "ENABLED=yes")],
            "ufw_status": None,
        }
        issues = UFWValidator("/tmp/ufw.conf").run_rules(data)
        duplicate = next(item for item in issues if item["code"] == "UFW_DUPLICATE_ENABLED")
        self.assertFalse(duplicate["repairable"])

    def test_concurrent_edit_aborts_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service.conf"
            path.write_bytes(b"value=old\n")
            fixes = [
                {"action": "replace", "line_number": 1, "content": "value=new", "expected_original": "value=old\n"}
            ]
            RepairManager.preview_fixes(str(path), fixes)
            path.write_bytes(b"value=changed\n")
            with self.assertRaises(RepairError):
                RepairManager.apply_fixes(str(path), fixes)

    def test_default_backup_is_not_adjacent_to_configuration(self) -> None:
        self.assertEqual(BackupManager().backup_dir, Path("/var/lib/lixet/backups"))

    def test_unconditional_verifier_is_not_success(self) -> None:
        self.assertFalse(LixetEngine._verify_true([]))

    def test_user_writable_path_executable_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / ("lixet-fake.exe" if os.name == "nt" else "lixet-fake")
            shutil.copy2(sys.executable, fake)
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(root)}):
                result = run_command(["lixet-fake", "-c", "print('untrusted')"])
            self.assertIsNone(result)

    def test_updater_has_no_mutable_branch_fallback(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b"mutable branch"

        updater = LixetUpdater(no_color=True)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(updater, "_download_latest_release", return_value=None),
                mock.patch("urllib.request.urlopen", return_value=Response()),
                self.assertRaises(RuntimeError),
            ):
                updater._download(Path(tmp))

    def test_semver_prerelease_numbers_are_ordered(self) -> None:
        self.assertLess(version_key("1.0.0-beta.1"), version_key("1.0.0-beta.2"))
        self.assertLess(version_key("1.0.0-rc.1"), version_key("1.0.0-rc.2"))

    def test_managed_resolver_has_no_repair(self) -> None:
        data = {"lines": [], "managed_resolver": "systemd-resolved"}
        issues = DNSValidator("/tmp/resolv.conf").run_rules(data)
        self.assertFalse(any(item["repairable"] for item in issues))


class ValidatorBaselineTests(unittest.TestCase):
    def test_missing_ssh_port_is_healthy_default(self) -> None:
        issues = SSHValidator("/tmp/sshd_config").run_rules({"lines": []})
        self.assertFalse(any(item["code"] == "SSH_MISSING_PORT" for item in issues))

    def test_nginx_accepts_compact_events_block(self) -> None:
        data = {"lines": [row(1, "events {}")], "config_test": None}
        issues = NginxValidator("/tmp/nginx.conf").run_rules(data)
        self.assertFalse(any(item["code"] == "NGINX_MISSING_EVENTS" for item in issues))

    def test_nginx_ignores_braces_inside_strings(self) -> None:
        data = {"lines": [row(1, "events {}"), row(2, 'log_format test "{";')], "config_test": None}
        issues = NginxValidator("/tmp/nginx.conf").run_rules(data)
        self.assertFalse(
            any(item["code"] in {"NGINX_UNCLOSED_BLOCK", "NGINX_UNMATCHED_CLOSE_BRACE"} for item in issues)
        )

    def test_systemd_unit_section_is_optional(self) -> None:
        unit = {
            "file_path": "/tmp/demo.service",
            "lines": [
                {**row(1, "[Service]"), "section": "Service", "key": None, "value": None},
                {**row(2, "Type=oneshot"), "section": "Service", "key": "Type", "value": "oneshot"},
            ],
        }
        issues = SystemdValidator("/tmp").run_rules({"units": [unit], "failed_units": None, "system_state": None})
        codes = {item["code"] for item in issues}
        self.assertNotIn("SYSTEMD_MISSING_UNIT_SECTION", codes)
        self.assertNotIn("SYSTEMD_MISSING_EXECSTART", codes)

    def test_empty_fstab_is_not_universally_broken(self) -> None:
        issues = FstabValidator("/tmp/fstab").run_rules({"lines": [], "findmnt_verify": None})
        self.assertFalse(any(item["code"] == "FSTAB_EMPTY" for item in issues))

    def test_fstab_pass_number_above_two_is_not_parser_error(self) -> None:
        data = {"lines": [row(1, "/dev/sda1 / ext4 defaults 0 3")], "findmnt_verify": None}
        issues = FstabValidator("/tmp/fstab").run_rules(data)
        self.assertFalse(any(item["code"] == "FSTAB_INVALID_NUMERIC_FIELDS" for item in issues))


if __name__ == "__main__":
    unittest.main()

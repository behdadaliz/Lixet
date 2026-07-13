# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Reliability regressions for conservative diagnosis, Doctor logs, and uninstall."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from core.doctor_log import DoctorLogWriter
from core.engine import InspectionResult, LixetEngine
from core.layout import LixetLayout
from core.uninstaller import LixetUninstaller
from tests.helpers import create_owned_install, row
from utils.ui import UI
from validators.fail2ban_validator import Fail2banValidator
from validators.ufw_validator import UFWValidator


class ConservativeDiagnosisTests(unittest.TestCase):
    def test_fail2ban_stock_filter_duplicates_are_not_reported_when_native_test_passes(self) -> None:
        data = {
            "config_test": {"returncode": 0, "evidence": "OK", "command": "fail2ban-client -t"},
            "runtime_status": None,
            "files": [
                {
                    "file_path": "/etc/fail2ban/filter.d/apache-auth.conf",
                    "lines": [
                        row(1, "[Definition]", "/etc/fail2ban/filter.d/apache-auth.conf"),
                        row(2, "failregex = ^bad one$", "/etc/fail2ban/filter.d/apache-auth.conf"),
                        row(3, "            ^bad two$", "/etc/fail2ban/filter.d/apache-auth.conf"),
                        row(4, "failregex = ^bad three$", "/etc/fail2ban/filter.d/apache-auth.conf"),
                    ],
                }
            ],
        }
        self.assertEqual(Fail2banValidator("/etc/fail2ban").run_rules(data), [])

    def test_fail2ban_failed_native_test_reports_evidence_only(self) -> None:
        path = "/etc/fail2ban/jail.local"
        data = {
            "config_test": {
                "returncode": 1,
                "evidence": f"ERROR Failed during configuration: {path}:2 bad option",
                "command": "fail2ban-client -t",
            },
            "runtime_status": None,
            "files": [{"file_path": path, "lines": [row(1, "[sshd]", path), row(2, "broken =", path)]}],
        }
        issues = Fail2banValidator("/etc/fail2ban").run_rules(data)
        self.assertEqual([item["code"] for item in issues], ["FAIL2BAN_CONFIG_TEST_FAILED"])
        self.assertIn(path, issues[0]["evidence"])

    def test_ufw_inactive_is_not_a_problem(self) -> None:
        issues = UFWValidator("/tmp/ufw.conf").run_rules(
            {
                "file_path": "/tmp/ufw.conf",
                "lines": [row(1, "ENABLED=no", "/tmp/ufw.conf")],
                "ufw_status": {"returncode": 0, "evidence": "Status: inactive", "command": "ufw status"},
            }
        )
        self.assertFalse(any(item["code"] == "UFW_INACTIVE" for item in issues))


class DoctorLogTests(unittest.TestCase):
    def test_doctor_log_redacts_secrets_removes_ansi_and_retains_newest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = DoctorLogWriter(root / "logs", root / "fallback", keep=2)
            session = {
                "summary": {"services_checked": 1, "errors": 1, "warnings": 0, "observations": 0},
                "results": [InspectionResult("ssh", "checked", "/tmp/sshd", [], {"config_test": None}, {})],
                "items": [
                    (
                        "ssh",
                        {
                            "code": "SSH_CONFIG_TEST_FAILED",
                            "severity": "high",
                            "file_path": "/tmp/sshd",
                            "line_number": 2,
                            "repair_level": "unsafe",
                            "confidence": "high",
                            "evidence": "\x1b[31mpassword = hunter2\x1b[0m",
                        },
                    )
                ],
                "observations": [],
                "repairs": ["No repairs attempted."],
            }
            paths = []
            for index in range(3):
                path, warning = writer.write(session)
                self.assertIsNone(warning)
                self.assertIsNotNone(path)
                renamed = path.with_name(f"doctor-20000101-00000{index}.log")
                path.rename(renamed)
                paths.append(renamed)
            writer._cleanup(root / "logs")
            logs = sorted((root / "logs").glob("doctor-*.log"))
            self.assertEqual(len(logs), 2)
            text = logs[-1].read_text(encoding="utf-8")
            self.assertNotIn("\x1b", text)
            self.assertNotIn("hunter2", text)
            self.assertIn("password=<redacted>", text)


class UninstallTests(unittest.TestCase):
    def _layout(self, root: Path) -> LixetLayout:
        return LixetLayout(
            install_dir=root / "opt" / "lixet",
            bin_path=root / "bin" / "lixet",
            state_dir=root / "var" / "lib" / "lixet",
            backup_dir=root / "var" / "lib" / "lixet" / "backups",
            log_dir=root / "var" / "log" / "lixet",
            lock_dir=root / "run" / "lock" / "lixet",
        )

    def test_uninstall_dry_run_and_apply_preserve_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = self._layout(root)
            create_owned_install(layout.install_dir, "0.3.0-beta")
            layout.backup_dir.mkdir(parents=True)
            backup = layout.backup_dir / "keep"
            backup.write_text("backup", encoding="utf-8")
            (layout.state_dir / "cache").mkdir()
            (layout.state_dir / "cache" / "tmp").write_text("x", encoding="utf-8")
            layout.log_dir.mkdir(parents=True)
            (layout.log_dir / "doctor-old.log").write_text("log", encoding="utf-8")
            layout.lock_dir.mkdir(parents=True)
            (layout.lock_dir / "update.lock").write_text("0", encoding="utf-8")

            dry = LixetUninstaller(layout, dry_run=True, ui=UI(no_color=True, stdin=io.StringIO("")))
            self.assertTrue(dry.plan())
            self.assertTrue(layout.install_dir.exists())
            self.assertTrue(backup.exists())

            LixetUninstaller(layout, ui=UI(no_color=True, stdin=io.StringIO(""))).apply(
                LixetUninstaller(layout).plan()
            )
            self.assertFalse(layout.install_dir.exists())
            self.assertFalse(layout.log_dir.exists())
            self.assertFalse(layout.lock_dir.exists())
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "backup")

    def test_uninstall_refuses_unowned_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp))
            layout.install_dir.mkdir(parents=True)
            (layout.install_dir / ".lixet-install.json").write_text(json.dumps({"project": "other"}), encoding="utf-8")
            with self.assertRaises(Exception):
                LixetUninstaller(layout).plan()


if __name__ == "__main__":
    unittest.main()

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""CLI contract, engine verification, and terminal reliability tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backup.manager import RollbackError
from cli.parser import parse_and_execute
from core.engine import InspectionResult, LixetEngine
from core.models import ExitCode
from repair.transaction import TransactionError
from tests.helpers import FakeRunner
from utils.command import CommandRunner
from utils.ui import UI
from validators.networking_validator import NetworkingValidator


class EngineTests(unittest.TestCase):
    def _engine(self, root: Path, config: Path, **kwargs) -> LixetEngine:
        return LixetEngine(
            config_path=str(config),
            no_color=True,
            backup_dir=root / "backups",
            lock_dir=root / "locks",
            runner=FakeRunner(),
            ui=kwargs.pop("ui", UI(no_color=True, stdin=io.StringIO(""))),
            **kwargs,
        )

    def test_dry_run_performs_zero_writes_and_zero_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            original = b"127.0.0.1 myhost\n::1 localhost\n"
            hosts.write_bytes(original)
            engine = self._engine(root, hosts, dry_run=True)
            with contextlib.redirect_stdout(io.StringIO()):
                code = engine.scan_service("networking")
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertEqual(hosts.read_bytes(), original)
            self.assertFalse((root / "backups").exists())

    def test_noninteractive_scan_never_prompts_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 myhost\n::1 localhost\n")
            engine = self._engine(root, hosts)
            with contextlib.redirect_stdout(io.StringIO()):
                code = engine.scan_service("networking")
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertEqual(hosts.read_bytes(), b"127.0.0.1 myhost\n::1 localhost\n")
            self.assertFalse((root / "backups").exists())

    def test_eof_during_interactive_selection_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 myhost\n::1 localhost\n")
            ui = UI(no_color=True, stdin=io.StringIO(""), force_interactive=True)
            engine = self._engine(root, hosts, ui=ui)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.scan_service("networking")
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertNotIn("Traceback", output.getvalue())

    def test_safe_repair_is_reinspected_and_manifest_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 myhost # keep\n::1 localhost\n")

            class CountingValidator(NetworkingValidator):
                calls = 0

                def run_rules(self, data):
                    type(self).calls += 1
                    return super().run_rules(data)

            engine = self._engine(root, hosts, yes=True)
            engine.supported_services["networking"]["validator"] = CountingValidator
            with contextlib.redirect_stdout(io.StringIO()):
                code = engine.scan_service("networking")
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn(b"myhost localhost # keep", hosts.read_bytes())
            self.assertGreaterEqual(CountingValidator.calls, 3)
            manifests = list((root / "backups").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["verification"], "internally verified")

    def test_safe_repair_adds_missing_ipv4_localhost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"::1 localhost ip6-localhost ip6-loopback\n")

            engine = self._engine(root, hosts, yes=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.scan_service("networking")

            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn("NET_MISSING_IPV4_LOCALHOST", output.getvalue())
            self.assertIn(b"127.0.0.1 localhost\n", hosts.read_bytes())
            manifests = list((root / "backups").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)

    def test_safe_repair_adds_missing_ipv6_localhost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 localhost alias # keep\n")

            engine = self._engine(root, hosts, yes=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.scan_service("networking")

            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn("NET_MISSING_IPV6_LOCALHOST", output.getvalue())
            data = hosts.read_bytes()
            self.assertIn(b"127.0.0.1 localhost alias # keep\n", data)
            self.assertIn(b"::1 localhost ip6-localhost ip6-loopback\n", data)
            manifests = list((root / "backups").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)

    def test_safe_repair_adds_ipv4_localhost_token_without_losing_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 myhost alias # keep\n::1 localhost\n")

            engine = self._engine(root, hosts, yes=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.scan_service("networking")

            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn("NET_IPV4_LOCALHOST_NAME_MISSING", output.getvalue())
            self.assertIn(b"127.0.0.1 myhost alias localhost # keep\n", hosts.read_bytes())
            manifests = list((root / "backups").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)

    def test_missing_external_verifier_never_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "sshd_config"
            config.write_bytes(b"BadOption yes\n")
            engine = self._engine(root, config, yes=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.scan_service("ssh")
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn("authoritative syntax validation was not run", output.getvalue())
            self.assertEqual(config.read_bytes(), b"BadOption yes\n")
            self.assertFalse((root / "backups").exists())

    def test_doctor_marks_missing_critical_files_and_unsupported_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = LixetEngine(
                no_color=True,
                filesystem_root=root,
                backup_dir=root / "backups",
                lock_dir=root / "locks",
                runner=FakeRunner(),
                ui=UI(no_color=True, stdin=io.StringIO("")),
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = engine.run_doctor()
            text = output.getvalue()
            self.assertEqual(code, ExitCode.ISSUES)
            self.assertIn("networking", text)
            self.assertIn("configuration missing", text)
            self.assertIn("unsupported environment", text)
            self.assertNotIn("No issues detected in completed checks", text)

    def test_exit_code_contract_for_usage_inspection_repair_and_rollback(self) -> None:
        engine = LixetEngine(no_color=True, runner=FakeRunner(), ui=UI(no_color=True, stdin=io.StringIO("")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(engine.show_services(), ExitCode.OK)
            self.assertEqual(engine.scan_service("not-a-service"), ExitCode.USAGE)

        failed = InspectionResult("ssh", "failed", "/tmp/x", [], None, {}, "injected")
        with mock.patch.object(engine, "_inspect", return_value=failed), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(engine.scan_service("ssh"), ExitCode.INSPECTION_FAILED)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts"
            hosts.write_bytes(b"127.0.0.1 host\n::1 localhost\n")
            repair_engine = self._engine(root, hosts, yes=True)
            with (
                mock.patch.object(repair_engine.transaction, "execute", side_effect=TransactionError("injected")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(repair_engine.scan_service("networking"), ExitCode.REPAIR_FAILED)
            rollback_engine = self._engine(root, hosts, yes=True)
            with (
                mock.patch.object(rollback_engine.transaction, "execute", side_effect=RollbackError("injected")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(rollback_engine.scan_service("networking"), ExitCode.ROLLBACK_FAILED)


class ParserAndUITests(unittest.TestCase):
    def test_doctor_config_is_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            parse_and_execute(["doctor", "--config", "/tmp/sshd_config"])
        self.assertEqual(raised.exception.code, ExitCode.USAGE)

    def test_services_command_returns_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parse_and_execute(["services", "--no-color"]), ExitCode.OK)

    def test_terminal_control_characters_are_sanitized(self) -> None:
        dirty = "safe\x1b[31mRED\x1b[0m\x00\x07"
        clean = UI.clean(dirty)
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("\x00", clean)
        self.assertNotIn("\x07", clean)
        self.assertEqual(clean, "safeRED??")


class CommandRunnerTests(unittest.TestCase):
    def _runner(self, max_output: int = 64 * 1024) -> tuple[CommandRunner, str]:
        executable = Path(sys.executable).resolve()
        runner = CommandRunner([executable.parent], require_root_owner=False, max_output=max_output)
        return runner, executable.name

    def test_injected_trusted_runner_uses_stable_locale_and_shell_false(self) -> None:
        runner, command = self._runner()
        result = runner.run([command, "-c", "import os; print(os.environ.get('LC_ALL'))"])
        self.assertIsNotNone(result)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["evidence"], "C")

    def test_output_is_bounded(self) -> None:
        runner, command = self._runner(max_output=32)
        result = runner.run([command, "-c", "print('x' * 1000)"])
        self.assertIn("output truncated", result["evidence"])
        self.assertLess(len(result["evidence"]), 100)

    def test_timeout_is_reported(self) -> None:
        runner, command = self._runner()
        result = runner.run([command, "-c", "import time; time.sleep(2)"], timeout=1)
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(result["timeout"])

    def test_inherited_path_is_not_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / ("fake.exe" if os.name == "nt" else "fake")
            fake.write_bytes(Path(sys.executable).read_bytes())
            fake.chmod(0o755)
            runner = CommandRunner([], require_root_owner=False)
            with mock.patch.dict(os.environ, {"PATH": str(tmp)}):
                self.assertIsNone(runner.run(["fake"]))


if __name__ == "__main__":
    unittest.main()

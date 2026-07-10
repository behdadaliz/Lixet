# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Public entry-point, release, backup, and diagnostic branch tests."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import install
import main
import manager
from backup.manager import BackupError, BackupManager, RollbackError
from cli.parser import parse_and_execute
from core.install_transaction import InstallError, InstallRollbackError
from core.models import ExitCode
from core.updater import LixetUpdater, UpdateError, UpdateNotNeeded
from core.version import (
    SemVer,
    VersionReporter,
    _status,
    fetch_github_version,
    normalize_version,
    parse_version,
    read_installed_version,
    select_latest_release,
    select_latest_tag,
)
from tests.helpers import row
from validators.dns_validator import DNSValidator
from validators.networking_validator import NetworkingValidator
from validators.nginx_validator import NginxValidator
from validators.ssh_validator import SSHValidator
from validators.systemd_validator import SystemdValidator


def semver(value: str) -> SemVer:
    parsed = parse_version(value)
    if parsed is None:
        raise AssertionError(f"invalid test version: {value}")
    return parsed


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class VersionContractTests(unittest.TestCase):
    def test_semver_format_equality_and_precedence(self) -> None:
        version = SemVer(1, 2, 3, ("rc", "2"), ("build", "7"))
        self.assertEqual(str(version), "1.2.3-rc.2+build.7")
        self.assertEqual(version, SemVer(1, 2, 3, ("rc", "2"), ("other",)))
        self.assertNotEqual(version, "1.2.3")
        self.assertLess(semver("1.0.0-1"), semver("1.0.0-alpha"))
        self.assertLess(semver("1.0.0-beta.2"), semver("1.0.0-beta.11"))
        self.assertLess(semver("1.0.0-rc.1"), semver("1.0.0"))

    def test_normalization_and_installed_version_fail_closed(self) -> None:
        self.assertIsNone(parse_version("01.2.3"))
        self.assertIsNone(normalize_version("release someday"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(read_installed_version(root), "unknown")
            (root / "VERSION").write_text("not-semver\n", encoding="utf-8")
            self.assertEqual(read_installed_version(root), "not-semver")

    def test_release_selection_respects_channel_and_ignores_drafts(self) -> None:
        items = [
            {"tag_name": "v1.0.0", "name": "one", "published_at": "2025-01-01"},
            {"tag_name": "v1.1.0", "name": "draft", "draft": True},
            {"tag_name": "bad", "name": "bad"},
            {"tag_name": "v1.0.1", "name": "two", "published_at": "2025-02-01"},
        ]
        self.assertEqual(select_latest_release(items, "stable")["version"], "1.0.1")
        self.assertIsNone(select_latest_release({}, "stable"))
        self.assertIsNone(select_latest_release([], "stable"))
        self.assertEqual(select_latest_tag([{"name": "v2.0.0"}])["version"], "2.0.0")
        self.assertIsNone(select_latest_tag({}))

    def test_version_reporter_prints_installed_latest_status_and_url(self) -> None:
        latest = {"version": "0.2.2-beta", "tag": "v0.2.2-beta", "url": "https://example.test/release"}
        output = io.StringIO()
        with (
            mock.patch("core.version.read_installed_version", return_value="0.2.0-beta.1"),
            mock.patch("core.version.fetch_github_version", return_value=latest),
            contextlib.redirect_stdout(output),
        ):
            self.assertTrue(VersionReporter(no_color=True).run())
        text = output.getvalue()
        self.assertIn("Installed version", text)
        self.assertIn("Latest release", text)
        self.assertIn("update available", text)
        self.assertIn("https://example.test/release", text)

    def test_version_status_and_fetch_paths(self) -> None:
        self.assertEqual(_status("bad", "1.0.0", True), "installed version unknown")
        self.assertEqual(_status("1.0.0", "bad", True), "unable to check")
        self.assertEqual(_status("1.0.0", "1.0.0", True), "up to date")
        self.assertEqual(_status("2.0.0", "1.0.0", True), "newer than latest release")
        self.assertEqual(_status("1.0.0", "1.0.1", False), "unable to check")
        with mock.patch("core.version._fetch_json", return_value=[{"tag_name": "v1.2.3"}]):
            self.assertEqual(fetch_github_version()["version"], "1.2.3")


class EntryPointTests(unittest.TestCase):
    def test_main_returns_parser_code_and_handles_input_end(self) -> None:
        with mock.patch("cli.parser.parse_and_execute", return_value=7), mock.patch.object(sys, "argv", ["lixet"]):
            self.assertEqual(main.main(), 7)
        output = io.StringIO()
        with (
            mock.patch("cli.parser.parse_and_execute", side_effect=EOFError),
            mock.patch.object(sys, "argv", ["lixet"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main.main(), ExitCode.ISSUES)
        self.assertIn("Input ended", output.getvalue())

    def test_main_handles_interrupt_and_broken_pipe(self) -> None:
        output = io.StringIO()
        with (
            mock.patch("cli.parser.parse_and_execute", side_effect=KeyboardInterrupt),
            mock.patch.object(sys, "argv", ["lixet"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main.main(), 130)
        self.assertIn("cancelled", output.getvalue())

        stream = mock.Mock()
        with (
            mock.patch("cli.parser.parse_and_execute", side_effect=BrokenPipeError),
            mock.patch.object(sys, "argv", ["lixet"]),
            mock.patch.object(sys, "stdout", stream),
        ):
            self.assertEqual(main.main(), 0)
        stream.close.assert_called_once()

    def test_cli_dispatches_top_level_flags_and_subcommands(self) -> None:
        reporter = mock.Mock()
        reporter.run.return_value = True
        updater = mock.Mock()
        updater.run.return_value = ExitCode.OK
        engine = mock.Mock()
        engine.scan_service.return_value = ExitCode.ISSUES
        engine.run_doctor.return_value = ExitCode.OK
        with mock.patch("core.version.VersionReporter", return_value=reporter):
            self.assertEqual(parse_and_execute(["--no-color", "--version"]), ExitCode.OK)
        with mock.patch("core.updater.LixetUpdater", return_value=updater):
            self.assertEqual(parse_and_execute(["--no-color", "--update"]), ExitCode.OK)
        with mock.patch("core.engine.LixetEngine", return_value=engine):
            self.assertEqual(parse_and_execute(["scan", "ssh", "--config", "/tmp/sshd", "--dry-run"]), ExitCode.ISSUES)
            self.assertEqual(parse_and_execute(["doctor", "-y"]), ExitCode.OK)
        engine.scan_service.assert_called_once_with("ssh")
        engine.run_doctor.assert_called_once()

    def test_installer_wrappers_and_error_codes(self) -> None:
        transaction = mock.Mock()
        with mock.patch("install.require_root"), mock.patch("install.InstallTransaction", return_value=transaction):
            with contextlib.redirect_stdout(io.StringIO()):
                install.install(force=True)
                install.uninstall(force=True)
        transaction.install.assert_called_once()
        transaction.uninstall.assert_called_once()
        self.assertIs(manager.BackupManager, BackupManager)

        with mock.patch("install.install", side_effect=InstallError("bad")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(install.main(["install"]), ExitCode.REPAIR_FAILED)
        with (
            mock.patch("install.uninstall", side_effect=InstallRollbackError("bad")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(install.main(["uninstall"]), ExitCode.ROLLBACK_FAILED)


class UpdaterContractTests(unittest.TestCase):
    def _updater(self, root: Path) -> LixetUpdater:
        installed = root / "install"
        installed.mkdir()
        (installed / "VERSION").write_text("0.2.0-beta.1\n", encoding="utf-8")
        return LixetUpdater(True, installed, root / "bin" / "lixet", root / "update.lock")

    def test_run_rejects_non_linux_non_root_and_missing_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updater = self._updater(Path(tmp))
            with mock.patch("core.updater.os", SimpleNamespace(name="nt")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(updater.run(), ExitCode.REPAIR_FAILED)
            with (
                mock.patch("core.updater.os", SimpleNamespace(name="posix", geteuid=lambda: 1000)),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(updater.run(), ExitCode.REPAIR_FAILED)
            updater.install_dir = Path(tmp) / "missing"
            with (
                mock.patch("core.updater.os", SimpleNamespace(name="posix", geteuid=lambda: 0)),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(updater.run(), ExitCode.REPAIR_FAILED)

    def test_run_maps_update_and_rollback_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updater = self._updater(Path(tmp))
            base = [
                mock.patch("core.updater.os", SimpleNamespace(name="posix", geteuid=lambda: 0)),
                mock.patch("core.updater._UpdateLock", return_value=contextlib.nullcontext()),
            ]
            with (
                base[0],
                base[1],
                mock.patch.object(updater, "_download", side_effect=UpdateNotNeeded("done")),
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(updater.run(), ExitCode.OK)

            with (
                mock.patch("core.updater.os", SimpleNamespace(name="posix", geteuid=lambda: 0)),
                mock.patch("core.updater._UpdateLock", return_value=contextlib.nullcontext()),
                mock.patch.object(updater, "_download", side_effect=InstallRollbackError("rollback")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(updater.run(), ExitCode.ROLLBACK_FAILED)

            with (
                mock.patch("core.updater.os", SimpleNamespace(name="posix", geteuid=lambda: 0)),
                mock.patch("core.updater._UpdateLock", return_value=contextlib.nullcontext()),
                mock.patch.object(updater, "_download", side_effect=UpdateError("network")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(updater.run(), ExitCode.REPAIR_FAILED)

    def test_complete_checksum_verified_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root)
            version = "0.2.0-beta.2"
            archive = b"verified archive"
            digest = hashlib.sha256(archive).hexdigest()
            release = [
                {
                    "tag_name": "v" + version,
                    "assets": [
                        {"name": f"lixet-{version}.zip", "browser_download_url": "https://example.test/archive"},
                        {
                            "name": f"lixet-{version}.zip.sha256",
                            "browser_download_url": "https://example.test/checksum",
                        },
                    ],
                }
            ]

            def opener(request, **_kwargs):
                if "releases" in request.full_url:
                    return FakeResponse(json.dumps(release).encode())
                if "checksum" in request.full_url:
                    return FakeResponse((digest + f"  lixet-{version}.zip\n").encode())
                return FakeResponse(archive)

            updater.opener = opener
            path, target = updater._download_latest_release(root)
            self.assertEqual(path.read_bytes(), archive)
            self.assertEqual(target, semver(version))

    def test_download_and_release_metadata_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root)
            (updater.install_dir / "VERSION").write_text("bad\n", encoding="utf-8")
            with self.assertRaises(UpdateError):
                updater._download_latest_release(root)
            with (
                mock.patch.object(updater, "_download_latest_release", return_value=None),
                self.assertRaises(UpdateError),
            ):
                updater._download(root)
            with self.assertRaises(UpdateError):
                updater._fetch_json("https://example.test", 10, 1)
            with self.assertRaises(UpdateError):
                updater._parse_checksum("xyz")
            release = {
                "assets": [
                    {"name": "lixet-1.0.0.zip", "browser_download_url": ""},
                    {"name": "sha256sums", "browser_download_url": ""},
                ]
            }
            with self.assertRaises(UpdateError):
                updater._release_assets(release, semver("1.0.0"))

    def test_archive_extracts_root_and_rejects_duplicates_or_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root)
            archive = root / "good.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("lixet/", b"")
                bundle.writestr("lixet/main.py", b"print('ok')\n")
                bundle.writestr("lixet/VERSION", b"1.0.0\n")
            source = updater._extract(archive, root / "work")
            self.assertEqual(source.name, "lixet")

            duplicate = root / "duplicate.zip"
            with zipfile.ZipFile(duplicate, "w") as bundle:
                bundle.writestr("root/main.py", b"one")
                bundle.writestr("ROOT/main.py", b"two")
            with self.assertRaises(UpdateError):
                updater._extract(duplicate, root / "dup-work")

            missing = root / "missing.zip"
            with zipfile.ZipFile(missing, "w") as bundle:
                bundle.writestr("root/VERSION", b"1.0.0")
            with self.assertRaises(UpdateError):
                updater._extract(missing, root / "missing-work")

    def test_archive_entry_types_hash_and_self_test_failures(self) -> None:
        directory = zipfile.ZipInfo("root/")
        directory.create_system = 3
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16
        self.assertEqual(LixetUpdater._validate_entry(directory)[1], "directory")
        bad_directory = zipfile.ZipInfo("root/")
        bad_directory.create_system = 3
        bad_directory.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(UpdateError):
            LixetUpdater._validate_entry(bad_directory)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data"
            path.write_bytes(b"abc")
            self.assertEqual(LixetUpdater._hash_file(path), hashlib.sha256(b"abc").hexdigest())
            with mock.patch("core.updater.compileall.compile_dir", return_value=False), self.assertRaises(UpdateError):
                LixetUpdater._self_test(Path(tmp))
            failed = SimpleNamespace(returncode=1, stderr=b"failed")
            with (
                mock.patch("core.updater.compileall.compile_dir", return_value=True),
                mock.patch("core.updater.subprocess.run", return_value=failed),
                self.assertRaises(UpdateError),
            ):
                LixetUpdater._self_test(Path(tmp))


class BackupContractTests(unittest.TestCase):
    def test_restore_success_verification_update_and_identifier_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            path.write_bytes(b"before\n")
            manager = BackupManager(root / "backups")
            manifest = Path(manager.create_backup(str(path), "test", ["one"]))
            path.write_bytes(b"after\n")
            self.assertTrue(manager.restore_backup(manifest.parent.name, str(path)))
            self.assertEqual(path.read_bytes(), b"before\n")
            manager.update_verification(str(manifest), "verified")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["verification"], "verified")

    def test_restore_rejects_wrong_target_and_invalid_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config"
            path.write_bytes(b"before\n")
            manager = BackupManager(root / "backups")
            manifest = Path(manager.create_backup(str(path)))
            with self.assertRaises(RollbackError):
                manager.restore_backup(str(manifest), str(root / "other"))
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["backup_id"] = "wrong"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(BackupError):
                manager.restore_backup(str(manifest))


class DiagnosticBranchTests(unittest.TestCase):
    def test_dns_reports_managed_invalid_duplicate_and_runtime_states(self) -> None:
        path = "/tmp/resolv.conf"
        rows = [
            row(1, "nameserver invalid", path),
            row(2, "nameserver 1.1.1.1", path),
            row(3, "nameserver 1.1.1.1", path),
            row(4, "nameserver 2001:4860:4860::8888", path),
            row(5, "search one.test", path),
            row(6, "domain two.test", path),
        ]
        snapshot = SimpleNamespace(is_symlink=True, original_path=path, resolved_path="/run/resolv.conf")
        data = {
            "lines": rows,
            "resolver_manager": "systemd-resolved",
            "snapshot": snapshot,
            "resolvectl": {"returncode": 1, "evidence": "denied", "command": "resolvectl status"},
        }
        issues = DNSValidator(path).run_rules(data)
        codes = {item["code"] for item in issues}
        self.assertTrue(
            {
                "DNS_MANAGED_RESOLVER",
                "DNS_INVALID_NAMESERVER",
                "DNS_DUPLICATE_NAMESERVER",
                "DNS_NAMESERVER_IGNORED",
                "DNS_SEARCH_OVERRIDE",
                "DNS_RESOLVECTL_FAILED",
            }.issubset(codes)
        )
        self.assertEqual(DNSValidator(path).run_rules({"missing_config": True})[0]["code"], "DNS_RESOLV_CONF_MISSING")

    def test_networking_reports_file_and_runtime_failures(self) -> None:
        rows = [
            row(1, "broken"),
            row(2, "bad host"),
            row(3, "127.0.0.1 localhost"),
            row(4, "127.0.0.1 localhost alias"),
            row(5, "::1 localhost"),
        ]
        data = {
            "lines": rows,
            "ip_route": {"returncode": 1, "evidence": "Permission denied", "command": "ip route"},
            "ip_addr": {"returncode": 1, "evidence": "failed", "command": "ip addr"},
            "ip_link": {"returncode": 1, "evidence": "failed", "command": "ip link"},
        }
        codes = {item["code"] for item in NetworkingValidator().run_rules(data)}
        self.assertTrue(
            {
                "HOSTS_MALFORMED_LINE",
                "HOSTS_INVALID_ADDRESS",
                "NET_DUPLICATE_LOCALHOST",
                "NET_ROUTE_PERMISSION_DENIED",
                "NET_ADDR_CHECK_FAILED",
                "NET_LINK_CHECK_FAILED",
            }.issubset(codes)
        )

        runtime = {
            "lines": [row(1, "127.0.0.1 localhost"), row(2, "::1 localhost")],
            "ip_route": {"returncode": 0, "evidence": "local only", "command": "ip route"},
            "ip_addr": {"returncode": 0, "evidence": "inet 127.0.0.1/8", "command": "ip addr"},
            "ip_link": {"returncode": 0, "evidence": "1: lo: <UP>", "command": "ip link"},
        }
        codes = {item["code"] for item in NetworkingValidator().run_rules(runtime)}
        self.assertTrue(
            {"NET_MISSING_DEFAULT_ROUTE", "NET_NO_NON_LOOPBACK_IP", "NET_NO_NON_LOOPBACK_LINK_UP"}.issubset(codes)
        )
        self.assertTrue(NetworkingValidator._has_non_loopback_ip("inet 10.0.0.2/24"))
        self.assertTrue(NetworkingValidator._has_non_loopback_up("2: eth0: <BROADCAST,UP>"))

    def test_nginx_reports_authoritative_and_structural_failures(self) -> None:
        path = "/tmp/nginx.conf"
        rows = [
            row(1, "}", path),
            row(2, "http {", path),
            row(3, "worker_processes zero;", path),
            row(4, "sendfile on", path),
            row(5, 'log_format main "# { ignored";', path),
        ]
        data = {
            "lines": rows,
            "include_errors": ["cycle"],
            "config_test": {"returncode": 1, "evidence": f"error in {path}:4", "command": "nginx -t"},
        }
        codes = {item["code"] for item in NginxValidator(path).run_rules(data)}
        self.assertTrue(
            {
                "NGINX_INCLUDE_ERROR",
                "NGINX_CONFIG_TEST_FAILED",
                "NGINX_UNMATCHED_CLOSE_BRACE",
                "NGINX_UNCLOSED_BLOCK",
                "NGINX_MISSING_SEMICOLON",
                "NGINX_INVALID_WORKER_PROCESSES",
                "NGINX_MISSING_EVENTS",
            }.issubset(codes)
        )
        self.assertNotIn("ignored", NginxValidator._code('x "ignored" # comment'))

    def test_ssh_reports_exact_bad_directive_and_invalid_values(self) -> None:
        path = "/tmp/sshd_config"
        rows = [
            {**row(1, "BadOption yes", path), "directive": "BadOption", "value": "yes", "in_match": False},
            {**row(2, "Port wrong", path), "directive": "Port", "value": "wrong", "in_match": False},
            {
                **row(3, "PermitRootLogin maybe", path),
                "directive": "PermitRootLogin",
                "value": "maybe",
                "in_match": False,
            },
            {
                **row(4, "PasswordAuthentication maybe", path),
                "directive": "PasswordAuthentication",
                "value": "maybe",
                "in_match": False,
            },
            {
                **row(5, "ListenAddress [::1]bad", path),
                "directive": "ListenAddress",
                "value": "[::1]bad",
                "in_match": False,
            },
            {**row(6, "Port 22", path), "directive": "Port", "value": "22", "in_match": False},
        ]
        data = {
            "lines": rows,
            "include_errors": ["depth exceeded"],
            "config_test": {
                "returncode": 1,
                "evidence": f"{path}: line 1: Bad configuration option: BadOption",
                "command": "sshd -t",
            },
        }
        issues = SSHValidator(path).run_rules(data)
        codes = {item["code"] for item in issues}
        self.assertTrue(
            {
                "SSH_INCLUDE_ERROR",
                "SSH_CONFIG_TEST_FAILED",
                "SSH_INVALID_PORT",
                "SSH_INVALID_PERMIT_ROOT_LOGIN",
                "SSH_INVALID_PASSWORDAUTHENTICATION",
                "SSH_INVALID_LISTEN_ADDRESS",
                "SSH_DUPLICATE_PORT",
            }.issubset(codes)
        )
        exact = next(item for item in issues if item["code"] == "SSH_CONFIG_TEST_FAILED")
        self.assertTrue(exact["repairable"])
        self.assertFalse(SSHValidator._valid_listen("[::1"))
        self.assertFalse(SSHValidator._valid_listen("host:70000"))

    def test_systemd_reports_runtime_verifier_and_unit_failures(self) -> None:
        def unit(path: str, rows: list[dict]) -> dict:
            return {"file_path": path, "lines": rows}

        units = [
            unit("/tmp/no-service.service", [{**row(1, "[Unit]"), "section": "Unit"}]),
            unit(
                "/tmp/bad.service",
                [
                    {**row(1, "[Service]"), "section": "Service"},
                    {**row(2, "Type=wrong"), "section": "Service", "key": "Type", "value": "wrong"},
                    {**row(3, "Restart=sometimes"), "section": "Service", "key": "Restart", "value": "sometimes"},
                    {**row(4, "ExecStart="), "section": "Service", "key": "ExecStart", "value": ""},
                    {
                        **row(5, "ExecStart=/definitely/missing"),
                        "section": "Service",
                        "key": "ExecStart",
                        "value": "/definitely/missing",
                    },
                ],
            ),
            unit(
                "/tmp/missing-exec.service",
                [{**row(1, "[Service]"), "section": "Service"}],
            ),
        ]
        data = {
            "units": units,
            "system_state": {"returncode": 1, "evidence": "degraded", "command": "systemctl is-system-running"},
            "failed_units": {"returncode": 0, "evidence": "demo.service failed", "command": "systemctl --failed"},
            "config_test": {"returncode": 1, "evidence": "bad unit", "command": "systemd-analyze verify"},
        }
        codes = {item["code"] for item in SystemdValidator().run_rules(data)}
        self.assertTrue(
            {
                "SYSTEMD_DEGRADED",
                "SYSTEMD_FAILED_UNITS",
                "SYSTEMD_VERIFY_FAILED",
                "SYSTEMD_MISSING_SERVICE_SECTION",
                "SYSTEMD_INVALID_TYPE",
                "SYSTEMD_INVALID_RESTART",
                "SYSTEMD_EMPTY_EXECSTART",
                "SYSTEMD_EXECSTART_NOT_FOUND",
                "SYSTEMD_MISSING_EXECSTART",
            }.issubset(codes)
        )
        unavailable = SystemdValidator().run_rules({"units": units[:1], "failed_units": None, "system_state": None})
        unavailable_codes = {item["code"] for item in unavailable}
        self.assertTrue({"SYSTEMD_COMMAND_UNAVAILABLE", "SYSTEMD_VERIFIER_UNAVAILABLE"}.issubset(unavailable_codes))


if __name__ == "__main__":
    unittest.main()

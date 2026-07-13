# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Failure-injection tests for install and update transactions."""

from __future__ import annotations

import io
import json
import stat
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from core.install_transaction import (
    MARKER_NAME,
    InstallError,
    InstallPhase,
    InstallTransaction,
)
from core.updater import LixetUpdater, UpdateError, UpdateNotNeeded, _UpdateLock
from core.version import normalize_version, parse_version, select_latest_release, version_key
from tests.helpers import create_owned_install, create_source_tree


class InstallerTests(unittest.TestCase):
    def test_failure_at_every_phase_preserves_previous_install(self) -> None:
        for phase in InstallPhase:
            with self.subTest(phase=phase.value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "source"
                installed = root / "opt" / "lixet"
                command = root / "bin" / "lixet"
                create_source_tree(source)
                create_owned_install(installed)

                def fail(current: InstallPhase, target: InstallPhase = phase) -> None:
                    if current == target:
                        raise RuntimeError(f"injected {target.value}")

                transaction = InstallTransaction(source, installed, command, phase_hook=fail)
                with (
                    mock.patch.object(InstallTransaction, "_link_command"),
                    self.assertRaises((InstallError, RuntimeError)),
                ):
                    transaction.install()
                self.assertEqual((installed / "sentinel").read_text(encoding="utf-8"), "old")
                leftovers = [
                    path.name for path in installed.parent.iterdir() if path.name.startswith(".lixet-install-")
                ]
                self.assertFalse(leftovers)

    def test_success_writes_ownership_marker_and_removes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "opt" / "lixet"
            command = root / "bin" / "lixet"
            create_source_tree(source)
            create_owned_install(installed)
            transaction = InstallTransaction(source, installed, command)
            with mock.patch.object(InstallTransaction, "_link_command"):
                transaction.install()
            self.assertTrue((installed / MARKER_NAME).is_file())
            self.assertFalse((installed / "sentinel").exists())
            self.assertFalse(any(path.name.startswith(".lixet-install-backup-") for path in installed.parent.iterdir()))

    def test_generated_local_junk_is_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "opt" / "lixet"
            command = root / "bin" / "lixet"
            create_source_tree(source)
            for name in (".agents", ".agent", ".codex", ".pytest_cache", "lixet.egg-info"):
                directory = source / name
                directory.mkdir()
                (directory / "state").write_text("local", encoding="utf-8")
            for name in (".env.local", "debug.log", "archive.zip", "module.pyc", "notes.tmp"):
                (source / name).write_text("local", encoding="utf-8")
            transaction = InstallTransaction(source, installed, command)
            with mock.patch.object(InstallTransaction, "_link_command"):
                transaction.install()
            for name in (
                ".agents",
                ".agent",
                ".codex",
                ".pytest_cache",
                "lixet.egg-info",
                ".env.local",
                "debug.log",
                "archive.zip",
                "module.pyc",
                "notes.tmp",
            ):
                self.assertFalse((installed / name).exists(), name)

    def test_unowned_install_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "lixet"
            create_source_tree(source)
            installed.mkdir()
            (installed / "private").write_text("keep", encoding="utf-8")
            with self.assertRaises(InstallError):
                InstallTransaction(source, installed, root / "bin" / "lixet").install()
            self.assertEqual((installed / "private").read_text(encoding="utf-8"), "keep")

    def test_unrelated_command_entry_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            command = root / "bin" / "lixet"
            create_source_tree(source)
            command.parent.mkdir()
            command.write_text("unrelated", encoding="utf-8")
            with self.assertRaises(InstallError):
                InstallTransaction(source, root / "install", command).install()
            self.assertEqual(command.read_text(encoding="utf-8"), "unrelated")

    def test_forced_regular_command_is_restored_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "opt" / "lixet"
            command = root / "bin" / "lixet"
            create_source_tree(source)
            command.parent.mkdir()
            command.write_text("original command\n", encoding="utf-8")

            def fail(phase: InstallPhase) -> None:
                if phase == InstallPhase.COMMAND_LINKED:
                    raise RuntimeError("injected link failure")

            def replace_command(_transaction: InstallTransaction, _main: Path) -> None:
                command.unlink()
                command.write_text("new command\n", encoding="utf-8")

            transaction = InstallTransaction(source, installed, command, force=True, phase_hook=fail)
            with (
                mock.patch.object(InstallTransaction, "_link_command", replace_command),
                self.assertRaises(InstallError),
            ):
                transaction.install()

            self.assertEqual(command.read_text(encoding="utf-8"), "original command\n")
            self.assertFalse(installed.exists())
            self.assertFalse(any(path.name.endswith(".backup") for path in command.parent.iterdir()))

    def test_required_path_must_have_exact_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_source_tree(root)
            (root / "VERSION").unlink()
            (root / "VERSION").mkdir()
            with self.assertRaises(InstallError):
                InstallTransaction._validate_tree(root)


class VersionTests(unittest.TestCase):
    def test_full_semver_prerelease_order(self) -> None:
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        ]
        self.assertEqual(sorted(ordered, key=version_key), ordered)

    def test_legacy_release_name_is_normalized_without_losing_number(self) -> None:
        self.assertEqual(normalize_version("Lixet Beta_0.3.0"), "0.3.0-beta")
        self.assertEqual(normalize_version("v1.2.3-beta2"), "1.2.3-beta.2")

    def test_stable_channel_excludes_prerelease(self) -> None:
        items = [
            {"tag_name": "v1.0.0", "name": "stable"},
            {"tag_name": "v1.1.0-beta.1", "name": "beta", "prerelease": True},
        ]
        self.assertEqual(select_latest_release(items, channel="stable")["version"], "1.0.0")
        self.assertEqual(select_latest_release(items, channel="prerelease")["version"], "1.1.0-beta.1")


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class UpdaterTests(unittest.TestCase):
    def _updater(self, root: Path, opener=None) -> LixetUpdater:
        install = root / "install"
        install.mkdir()
        (install / "VERSION").write_text("0.3.0-alpha\n", encoding="utf-8")
        return LixetUpdater(
            no_color=True,
            install_dir=install,
            bin_path=root / "bin" / "lixet",
            lock_path=root / "locks" / "update.lock",
            opener=opener,
        )

    def test_same_version_does_not_download_or_reinstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = [{"tag_name": "v0.3.0-alpha", "name": "same", "assets": []}]
            updater = self._updater(root, opener=lambda *_args, **_kwargs: FakeResponse(json.dumps(release).encode()))
            with self.assertRaises(UpdateNotNeeded):
                updater._download_latest_release(root)

    def test_downgrade_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = [{"tag_name": "v0.3.0-alpha", "name": "old", "assets": []}]
            updater = self._updater(root, opener=lambda *_args, **_kwargs: FakeResponse(json.dumps(release).encode()))
            (updater.install_dir / "VERSION").write_text("0.3.0-beta\n", encoding="utf-8")
            with self.assertRaises(UpdateError):
                updater._download_latest_release(root)

    def test_release_requires_github_source_archive_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = [{"tag_name": "v0.3.0-beta", "name": "newer"}]
            updater = self._updater(root, opener=lambda *_args, **_kwargs: FakeResponse(json.dumps(release).encode()))
            with self.assertRaises(UpdateError):
                updater._download_latest_release(root)

    def test_release_source_archive_is_downloaded_from_zipball_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "0.3.0-beta"
            archive = b"release source archive"
            release = [
                {
                    "tag_name": "v" + version,
                    "name": version,
                    "zipball_url": "https://example.invalid/source.zip",
                }
            ]

            def opener(request, **_kwargs):
                url = request.full_url
                if "releases" in url:
                    return FakeResponse(json.dumps(release).encode())
                self.assertEqual(url, "https://example.invalid/source.zip")
                return FakeResponse(archive)

            updater = self._updater(root, opener)
            path, target = updater._download_latest_release(root)
            self.assertEqual(path.read_bytes(), archive)
            self.assertEqual(target, parse_version(version))

    def test_download_size_limit_is_enforced_and_partial_file_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root, opener=lambda *_args, **_kwargs: FakeResponse(b"123456"))
            destination = root / "archive.zip"
            with self.assertRaises(UpdateError):
                updater._download_file("https://example.invalid/archive", destination, 5, 2)
            self.assertFalse(destination.exists())

    def test_network_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updater = self._updater(Path(tmp), opener=mock.Mock(side_effect=urllib.error.URLError("offline")))
            with self.assertRaises(UpdateError):
                updater._fetch_json("https://example.invalid", 100, 1)

    def test_archive_rejects_traversal_absolute_symlink_and_special_files(self) -> None:
        unsafe = ["../escape", "/absolute", "root/../../escape"]
        for name in unsafe:
            with self.subTest(name=name):
                with self.assertRaises(UpdateError):
                    LixetUpdater._validate_entry(zipfile.ZipInfo(name))
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            entry = zipfile.ZipInfo("root/unsafe")
            entry.create_system = 3
            entry.external_attr = mode << 16
            with self.assertRaises(UpdateError):
                LixetUpdater._validate_entry(entry)

    def test_oversized_archive_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root)
            updater.MAX_FILE_SIZE = 8
            archive = root / "large.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("root/main.py", b"x" * 9)
            with self.assertRaises(UpdateError):
                updater._extract(archive, root / "extract-work")

    def test_too_many_archive_entries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            updater = self._updater(root)
            updater.MAX_ENTRIES = 1
            archive = root / "many.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("root/main.py", b"print('x')")
                bundle.writestr("root/VERSION", b"0.3.0-beta")
            with self.assertRaises(UpdateError):
                updater._extract(archive, root / "extract-work")

    def test_version_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            create_source_tree(source, "0.3.0-alpha")
            updater = self._updater(root)
            with self.assertRaises(UpdateError):
                updater._validate_source(source, parse_version("0.3.0-beta"))

    def test_staged_source_compile_and_cli_self_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            create_source_tree(source)
            LixetUpdater._self_test(source)

    def test_update_lock_rejects_concurrent_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.lock"
            with _UpdateLock(path):
                with self.assertRaises(UpdateError):
                    with _UpdateLock(path):
                        pass


if __name__ == "__main__":
    unittest.main()

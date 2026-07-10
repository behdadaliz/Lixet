# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Release-only, checksum-verified self updates."""

from __future__ import annotations

import compileall
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from core.install_transaction import InstallError, InstallRollbackError, InstallTransaction
from core.models import ExitCode
from core.version import SemVer, read_installed_version, select_latest_release, version_key
from utils.ui import UI


class UpdateError(RuntimeError):
    """Raised when an update fails security or integrity checks."""


class UpdateNotNeeded(UpdateError):
    """Raised when the installed release is already current."""


class LixetUpdater:
    INSTALL_DIR = Path("/opt/lixet")
    BIN_PATH = Path("/usr/local/bin/lixet")
    LOCK_PATH = Path("/run/lock/lixet/update.lock")
    RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases?per_page=50"
    MAX_METADATA = 1024 * 1024
    MAX_CHECKSUM = 4096
    MAX_DOWNLOAD = 20 * 1024 * 1024
    MAX_ENTRIES = 512
    MAX_FILE_SIZE = 2 * 1024 * 1024
    MAX_EXTRACTED = 16 * 1024 * 1024
    CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        no_color: bool = False,
        install_dir: str | Path | None = None,
        bin_path: str | Path | None = None,
        lock_path: str | Path | None = None,
        opener=None,
    ) -> None:
        self.ui = UI(no_color=no_color)
        self.install_dir = Path(install_dir) if install_dir is not None else self.INSTALL_DIR
        self.bin_path = Path(bin_path) if bin_path is not None else self.BIN_PATH
        self.lock_path = Path(lock_path) if lock_path is not None else self.LOCK_PATH
        self.opener = opener or urllib.request.urlopen
        self.force = False

    def run(self) -> ExitCode:
        self.ui.banner("Lixet Update")
        self.ui.kv("Target", str(self.install_dir))
        if os.name != "posix":
            self.ui.status("error", "Update is supported on Linux installations only.")
            return ExitCode.REPAIR_FAILED
        if getattr(os, "geteuid", lambda: -1)() != 0:
            self.ui.status("error", "Update requires root privileges. Try: sudo lixet --update")
            return ExitCode.REPAIR_FAILED
        if not self.install_dir.is_dir():
            self.ui.status("error", f"Installed version not found: {self.install_dir}")
            return ExitCode.REPAIR_FAILED

        try:
            with _UpdateLock(self.lock_path):
                with tempfile.TemporaryDirectory(prefix="lixet-update-") as tmp:
                    tmp_path = Path(tmp)
                    archive, target = self._download(tmp_path)
                    source = self._extract(archive, tmp_path)
                    self._validate_source(source, target)
                    self._self_test(source)
                    InstallTransaction(source, self.install_dir, self.bin_path).install()
        except UpdateNotNeeded as exc:
            self.ui.status("ok", str(exc))
            return ExitCode.OK
        except InstallRollbackError as exc:
            self.ui.status("critical", f"Update rollback failed: {exc}")
            return ExitCode.ROLLBACK_FAILED
        except (UpdateError, InstallError, OSError, zipfile.BadZipFile) as exc:
            self.ui.status("error", f"Update failed: {exc}")
            return ExitCode.REPAIR_FAILED

        self.ui.status("ok", "Lixet updated successfully.")
        self.ui.kv("Installed", read_installed_version(self.install_dir))
        return ExitCode.OK

    def _download(self, tmp_path: Path) -> tuple[Path, SemVer]:
        result = self._download_latest_release(tmp_path)
        if result is None:
            raise UpdateError("No release matching the installed update channel is available.")
        return result

    def _download_latest_release(self, tmp_path: Path) -> tuple[Path, SemVer] | None:
        installed = version_key(read_installed_version(self.install_dir))
        if installed is None:
            raise UpdateError("Installed VERSION is invalid; refusing an automatic update.")
        channel = "prerelease" if installed.prerelease else "stable"
        releases = self._fetch_json(self.RELEASES_URL, self.MAX_METADATA, timeout=15)
        release = select_latest_release(releases, channel=channel)
        if not release:
            return None
        target = version_key(str(release["version"]))
        if target is None:
            raise UpdateError("Release tag is not valid Semantic Versioning.")
        if target == installed:
            raise UpdateNotNeeded(f"Lixet {installed} is already installed.")
        if target < installed and not self.force:
            raise UpdateError(f"Refusing downgrade from {installed} to {target}.")

        archive_asset, checksum_asset = self._release_assets(release, target)
        checksum_text = self._download_bytes(str(checksum_asset["browser_download_url"]), self.MAX_CHECKSUM, timeout=20)
        expected = self._parse_checksum(
            checksum_text.decode("ascii", errors="strict"),
            str(archive_asset["name"]),
        )
        archive = tmp_path / f"lixet-{target}.zip"
        self._download_file(str(archive_asset["browser_download_url"]), archive, self.MAX_DOWNLOAD, timeout=30)
        actual = self._hash_file(archive)
        if actual != expected:
            raise UpdateError("Release archive checksum mismatch.")
        return archive, target

    def _release_assets(self, release: dict, version: SemVer) -> tuple[dict, dict]:
        archive_name = f"lixet-{version}.zip".lower()
        checksum_names = {f"{archive_name}.sha256", "sha256sums"}
        archive = None
        checksum = None
        for asset in release.get("assets", []):
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            if name == archive_name:
                archive = asset
            elif name in checksum_names:
                checksum = asset
        if not archive or not checksum:
            raise UpdateError(f"Release must provide {archive_name} and a SHA-256 checksum asset.")
        if not archive.get("browser_download_url") or not checksum.get("browser_download_url"):
            raise UpdateError("Release asset download URL is missing.")
        return archive, checksum

    def _fetch_json(self, url: str, limit: int, timeout: int) -> object:
        data = self._download_bytes(url, limit, timeout)
        try:
            return json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise UpdateError(f"Invalid GitHub release metadata: {exc}") from exc

    def _download_bytes(self, url: str, limit: int, timeout: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Lixet-Updater", "Accept": "application/vnd.github+json"},
        )
        try:
            with self.opener(request, timeout=timeout) as response:
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(self.CHUNK_SIZE, limit + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise UpdateError(f"Download exceeds {limit} bytes.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.URLError as exc:
            raise UpdateError(f"Download failed: {exc}") from exc

    def _download_file(self, url: str, destination: Path, limit: int, timeout: int) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Lixet-Updater"})
        total = 0
        try:
            with self.opener(request, timeout=timeout) as response, destination.open("xb") as output:
                while True:
                    chunk = response.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise UpdateError(f"Release archive exceeds {limit} bytes.")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except urllib.error.URLError as exc:
            raise UpdateError(f"Release download failed: {exc}") from exc
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def _extract(self, archive: Path, tmp_path: Path) -> Path:
        destination = tmp_path / "source"
        destination.mkdir(mode=0o700, parents=True)
        total = 0
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > self.MAX_ENTRIES:
                raise UpdateError("Release archive contains too many entries.")
            seen: set[str] = set()
            for entry in entries:
                relative, kind = self._validate_entry(entry)
                key = relative.as_posix().casefold()
                if key in seen:
                    raise UpdateError(f"Archive contains a duplicate path: {entry.filename}")
                seen.add(key)
                total += entry.file_size
                if entry.file_size > self.MAX_FILE_SIZE:
                    raise UpdateError(f"Archive entry is too large: {entry.filename}")
                if total > self.MAX_EXTRACTED:
                    raise UpdateError("Release archive expands beyond the allowed total size.")
                target = destination.joinpath(*relative.parts)
                if kind == "directory":
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                try:
                    with bundle.open(entry) as source, target.open("xb") as output:
                        while True:
                            chunk = source.read(self.CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > entry.file_size or written > self.MAX_FILE_SIZE:
                                raise UpdateError(f"Archive entry exceeded its declared size: {entry.filename}")
                            output.write(chunk)
                except (RuntimeError, NotImplementedError) as exc:
                    raise UpdateError(f"Archive entry cannot be safely extracted: {entry.filename}") from exc
                if written != entry.file_size:
                    raise UpdateError(f"Archive entry size mismatch: {entry.filename}")

        roots = [path for path in destination.iterdir() if path.is_dir() and (path / "main.py").is_file()]
        if len(roots) == 1:
            return roots[0]
        if (destination / "main.py").is_file():
            return destination
        raise UpdateError("Release archive must contain exactly one Lixet source root.")

    @staticmethod
    def _validate_entry(entry: zipfile.ZipInfo) -> tuple[PurePosixPath, str]:
        name = entry.filename
        if not name or "\x00" in name or "\\" in name:
            raise UpdateError("Archive contains an invalid path.")
        relative = PurePosixPath(name)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise UpdateError(f"Archive contains an unsafe path: {name}")
        mode = (entry.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        is_directory = entry.is_dir()
        if is_directory:
            if file_type not in {0, stat.S_IFDIR}:
                raise UpdateError(f"Archive directory has an unsafe type: {name}")
            return relative, "directory"
        if file_type not in {0, stat.S_IFREG}:
            raise UpdateError(f"Archive contains a symlink or special file: {name}")
        return relative, "file"

    @staticmethod
    def _parse_checksum(text: str, archive_name: str | None = None) -> str:
        bare: list[str] = []
        matches: list[str] = []
        for line in text.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            token = parts[0]
            if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
                raise UpdateError("Checksum asset does not contain a valid SHA-256 digest.")
            digest = token.lower()
            if len(parts) == 1:
                bare.append(digest)
                continue
            if archive_name is None:
                continue
            name = parts[-1].lstrip("*")
            if name == archive_name:
                matches.append(digest)

        if archive_name is not None and matches:
            if len(set(matches)) != 1 or len(matches) > 1:
                raise UpdateError("Checksum asset contains duplicate entries for the release archive.")
            return matches[0]
        if len(bare) == 1:
            return bare[0]
        raise UpdateError("Checksum asset does not contain a checksum for the release archive.")

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_source(self, source: Path, target: SemVer) -> None:
        InstallTransaction._validate_tree(source)
        raw = (source / "VERSION").read_text(encoding="utf-8").strip()
        parsed = version_key(raw)
        if parsed != target:
            raise UpdateError(f"VERSION '{raw}' does not match release tag '{target}'.")

    @staticmethod
    def _self_test(source: Path) -> None:
        if not compileall.compile_dir(source, quiet=2, force=True):
            raise UpdateError("Python compile check failed in update staging.")
        env = {"LC_ALL": "C", "LANG": "C", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            result = subprocess.run(
                [sys.executable, "-B", "main.py", "--no-color", "services"],
                cwd=source,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"Staged CLI self-test could not run: {exc}") from exc
        if result.returncode != 0:
            evidence = result.stderr[:4096].decode("utf-8", errors="replace")
            raise UpdateError(f"Staged CLI self-test failed: {evidence}")


class _UpdateLock:
    _thread_lock = threading.Lock()

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def __enter__(self):
        if not self._thread_lock.acquire(blocking=False):
            raise UpdateError("Another Lixet update is already running.")
        try:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            handle = self.path.open("a+b")
            self.handle = handle
            if self.path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            _lock_handle(handle)
            return self
        except BaseException as exc:
            if self.handle:
                self.handle.close()
                self.handle = None
            self._thread_lock.release()
            if isinstance(exc, UpdateError):
                raise
            raise UpdateError("Another Lixet update is already running.") from exc

    def __exit__(self, *_args) -> None:
        try:
            if self.handle:
                _unlock_handle(self.handle)
                self.handle.close()
        finally:
            self.handle = None
            self._thread_lock.release()


def _lock_handle(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl" if os.name == "posix" else "msvcrt")
    if os.name == "posix":
        module.flock(handle.fileno(), module.LOCK_EX | module.LOCK_NB)
        return
    module.locking(handle.fileno(), module.LK_NBLCK, 1)


def _unlock_handle(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl" if os.name == "posix" else "msvcrt")
    if os.name == "posix":
        module.flock(handle.fileno(), module.LOCK_UN)
        return
    handle.seek(0)
    module.locking(handle.fileno(), module.LK_UNLCK, 1)

# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Self-update support for installed Lixet copies."""

from __future__ import annotations

import os
import json
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from utils.ui import UI


class LixetUpdater:
    """Download the latest GitHub source and replace /opt/lixet safely."""

    INSTALL_DIR = Path("/opt/lixet")
    BIN_PATH = Path("/usr/local/bin/lixet")
    RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases"
    SOURCES = (
        ("main", "https://github.com/behdadaliz/Lixet/archive/refs/heads/main.zip"),
        ("master", "https://github.com/behdadaliz/Lixet/archive/refs/heads/master.zip"),
    )
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "developer", "docker", "tests"}
    SKIP_NAMES = {".env"}

    def __init__(self, no_color: bool = False) -> None:
        self.ui = UI(no_color=no_color)

    def run(self) -> bool:
        self.ui.banner("Lixet Update", "Downloading the latest GitHub version")
        if os.name != "posix":
            self.ui.status("error", "Update is supported on Linux installations only.")
            return False
        if os.geteuid() != 0:
            self.ui.status("error", "Update requires root privileges. Try: sudo lixet --update")
            return False
        if not self.INSTALL_DIR.exists():
            self.ui.status("error", f"Installed copy not found: {self.INSTALL_DIR}")
            self.ui.status("info", "Install Lixet first with: sudo sh install.sh")
            return False

        try:
            with tempfile.TemporaryDirectory(prefix="lixet-update-") as tmp:
                tmp_path = Path(tmp)
                archive = self._download(tmp_path)
                src = self._extract(archive, tmp_path)
                self._replace_install(src)
        except Exception as exc:
            self.ui.status("error", f"Update failed: {exc}")
            return False

        self.ui.status("ok", "Lixet updated successfully.")
        self.ui.kv("Command", "lixet")
        return True

    def _download(self, tmp_path: Path) -> Path:
        release_archive = self._download_latest_release(tmp_path)
        if release_archive:
            return release_archive

        last_error: Exception | None = None
        for branch, url in self.SOURCES:
            archive = tmp_path / f"lixet-{branch}.zip"
            self.ui.status("info", f"Checking GitHub branch: {branch}")
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Lixet-Updater"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    archive.write_bytes(response.read())
                self.ui.status("ok", f"Downloaded latest source from {branch}.")
                return archive
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 404:
                    continue
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                continue
        raise RuntimeError(f"Could not download update archive: {last_error}")

    def _download_latest_release(self, tmp_path: Path) -> Path | None:
        try:
            request = urllib.request.Request(self.RELEASES_URL, headers={"User-Agent": "Lixet-Updater"})
            with urllib.request.urlopen(request, timeout=15) as response:
                releases = json.loads(response.read().decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
            return None
        if not isinstance(releases, list) or not releases:
            return None

        item = releases[0]
        url = item.get("zipball_url")
        name = item.get("name") or item.get("tag_name") or "latest release"
        if not url:
            return None

        archive = tmp_path / "lixet-release.zip"
        self.ui.status("info", f"Checking GitHub release: {name}")
        request = urllib.request.Request(str(url), headers={"User-Agent": "Lixet-Updater"})
        with urllib.request.urlopen(request, timeout=30) as response:
            archive.write_bytes(response.read())
        self.ui.status("ok", f"Downloaded {name} from GitHub releases.")
        return archive

    def _extract(self, archive: Path, tmp_path: Path) -> Path:
        extract_dir = tmp_path / "src"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        roots = [path for path in extract_dir.iterdir() if path.is_dir() and (path / "main.py").exists()]
        if not roots:
            raise RuntimeError("Downloaded archive does not contain a Lixet entry point.")
        return roots[0]

    def _replace_install(self, src: Path) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self.INSTALL_DIR.with_name(f".lixet-update-backup-{stamp}")
        self.ui.status("info", f"Preparing installed copy: {self.INSTALL_DIR}")
        shutil.move(self.INSTALL_DIR, backup)
        try:
            shutil.copytree(src, self.INSTALL_DIR, ignore=self._ignore)
            main_script = self.INSTALL_DIR / "main.py"
            if not main_script.exists():
                raise RuntimeError("Updated copy is missing main.py.")
            mode = stat.S_IMODE(main_script.stat().st_mode)
            main_script.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if self.BIN_PATH.exists() or self.BIN_PATH.is_symlink():
                self.BIN_PATH.unlink()
            self.BIN_PATH.symlink_to(main_script)
        except Exception:
            if self.INSTALL_DIR.exists():
                shutil.rmtree(self.INSTALL_DIR)
            shutil.move(backup, self.INSTALL_DIR)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)

    def _ignore(self, _src: str, names: list[str]) -> set[str]:
        return {name for name in names if self._skip(name)}

    def _skip(self, name: str) -> bool:
        if name in self.SKIP_DIRS or name in self.SKIP_NAMES:
            return True
        if name.endswith(".pyc"):
            return True
        if name.endswith(".bak") or ".lixet." in name and name.endswith(".bak"):
            return True
        if name.startswith(".env."):
            return True
        return False

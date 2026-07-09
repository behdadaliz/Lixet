# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Version reporting and remote release checks."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from utils.ui import UI

RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases"
TAGS_URL = "https://api.github.com/repos/behdadaliz/Lixet/tags"


class VersionReporter:
    """Show the installed version and optional latest release."""

    def __init__(self, no_color: bool = False) -> None:
        self.ui = UI(no_color=no_color)

    def run(self) -> bool:
        installed = read_installed_version()
        latest = fetch_github_version()
        latest_version = latest["version"] if latest else "not available"
        status = _status(installed, latest_version, latest is not None)

        self.ui.banner("Lixet Version")
        self._line("Installed version", installed)
        self._line("Latest release", latest_version)
        self._line("Status", status)
        print()
        print(self.ui.c("Update command:", self.ui.BOLD + self.ui.CYAN))
        print(f"  {self.ui.c('sudo lixet --update', self.ui.BOLD)}")
        return True

    def _line(self, key: str, value: str) -> None:
        print(f"{self.ui.c(key.ljust(18), self.ui.BOLD + self.ui.CYAN)}: {value}")


def read_installed_version(root: Path | None = None) -> str:
    base = root or Path(__file__).resolve().parents[1]
    version_file = base / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return normalize_version(version) or version or "unknown"


def fetch_github_version(timeout: int = 6) -> dict | None:
    release = _fetch_json(RELEASES_URL, timeout)
    if isinstance(release, list) and release:
        item = release[0]
        raw_tag = str(item.get("tag_name") or "").strip()
        raw_name = str(item.get("name") or "").strip()
        version = normalize_version(raw_tag) or normalize_version(raw_name)
        if version:
            return {
                "version": version,
                "url": item.get("html_url"),
            }

    tags = _fetch_json(TAGS_URL, timeout)
    if isinstance(tags, list) and tags:
        version = normalize_version(str(tags[0].get("name") or "").strip())
        if version:
            tag = str(tags[0].get("name") or "").strip()
            return {
                "version": version,
                "url": f"https://github.com/behdadaliz/Lixet/tree/{tag}" if tag else None,
            }
    return None


def _fetch_json(url: str, timeout: int) -> object | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Lixet-Version-Check"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
        return None


def normalize_version(text: str) -> str | None:
    clean = text.strip().lower().replace("_", "-")
    match = re.search(r"v?(\d+(?:\.\d+){1,3})(?:[-\s]*(alpha|beta|rc)(?:[-\s]*\d+)?)?", clean)
    if not match:
        return None
    version = match.group(1)
    label = match.group(2)
    if label:
        return f"{version}-{label}"
    if "alpha" in clean:
        return f"{version}-alpha"
    if "beta" in clean:
        return f"{version}-beta"
    if "rc" in clean:
        return f"{version}-rc"
    return version


def _status(installed: str, latest: str, checked: bool) -> str:
    if not checked:
        return "unable to check"
    if latest == "not available":
        return "release not published"
    if installed == "unknown":
        return "installed version unknown"
    if installed == latest:
        return "up to date"
    return "update available"

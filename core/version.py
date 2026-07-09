# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Version reporting and remote release checks."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from utils.ui import UI

RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases?per_page=50"
TAGS_URL = "https://api.github.com/repos/behdadaliz/Lixet/tags?per_page=50"


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
    releases = _fetch_json(RELEASES_URL, timeout)
    latest = select_latest_release(releases)
    if latest:
        return latest

    tags = _fetch_json(TAGS_URL, timeout)
    latest_tag = select_latest_tag(tags)
    if latest_tag:
        return latest_tag
    return None


def select_latest_release(items: object) -> dict | None:
    if not isinstance(items, list):
        return None

    candidates = []
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info(item)
        if not info:
            continue
        candidates.append((version_key(info["version"]), str(item.get("published_at") or item.get("created_at") or ""), info))

    candidates = [item for item in candidates if item[0] is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def select_latest_tag(items: object) -> dict | None:
    if not isinstance(items, list):
        return None

    candidates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("name") or "").strip()
        version = normalize_version(tag)
        key = version_key(version or "")
        if not version or key is None:
            continue
        candidates.append((key, tag, {
            "version": version,
            "display": version,
            "url": f"https://github.com/behdadaliz/Lixet/tree/{tag}",
            "tag": tag,
            "zipball_url": None,
        }))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][2]


def _release_info(item: dict) -> dict | None:
    raw_tag = str(item.get("tag_name") or "").strip()
    raw_name = str(item.get("name") or "").strip()
    version = normalize_version(raw_tag) or normalize_version(raw_name)
    if not version:
        return None
    return {
        "version": version,
        "display": version,
        "url": item.get("html_url"),
        "tag": raw_tag,
        "zipball_url": item.get("zipball_url"),
    }


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


def version_key(text: str) -> tuple[int, int, int, int, int] | None:
    version = normalize_version(text)
    if not version:
        return None
    match = re.match(r"(\d+(?:\.\d+){1,3})(?:-(alpha|beta|rc))?$", version)
    if not match:
        return None
    nums = [int(part) for part in match.group(1).split(".")]
    nums.extend([0] * (4 - len(nums)))
    stage = {"alpha": 0, "beta": 1, "rc": 2, None: 3}[match.group(2)]
    return nums[0], nums[1], nums[2], nums[3], stage


def _status(installed: str, latest: str, checked: bool) -> str:
    if not checked:
        return "unable to check"
    installed_key = version_key(installed)
    latest_key = version_key(latest)
    if installed_key is None:
        return "installed version unknown"
    if latest_key is None:
        return "unable to check"
    if installed_key == latest_key:
        return "up to date"
    if installed_key < latest_key:
        return "update available"
    return "newer than latest release"

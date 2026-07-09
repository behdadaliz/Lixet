# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Version reporting and remote update checks."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from utils.ui import UI

RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases"
TAGS_URL = "https://api.github.com/repos/behdadaliz/Lixet/tags"


class VersionReporter:
    """Show the latest GitHub version and update hint."""

    def __init__(self, no_color: bool = False) -> None:
        self.ui = UI(no_color=no_color)

    def run(self) -> bool:
        self.ui.banner("Lixet Version", "Checking GitHub release information")
        latest = fetch_github_version()
        if not latest:
            self.ui.status("warn", "Could not read the latest version name from GitHub.")
            return True

        self.ui.kv("GitHub version", latest["name"])
        self.ui.kv("Source", latest["source"])
        if latest.get("url"):
            self.ui.kv("URL", latest["url"])
        self.ui.status("info", "If your installed copy is older, update it.")
        self.ui.kv("Update", "sudo lixet --update")
        return True


def fetch_github_version(timeout: int = 6) -> dict | None:
    release = _fetch_json(RELEASES_URL, timeout)
    if isinstance(release, list) and release:
        item = release[0]
        name = str(item.get("name") or item.get("tag_name") or "").strip()
        if name:
            return {
                "name": name,
                "source": "GitHub release",
                "url": item.get("html_url"),
            }

    tags = _fetch_json(TAGS_URL, timeout)
    if isinstance(tags, list) and tags:
        name = str(tags[0].get("name") or "").strip()
        if name:
            return {
                "name": name,
                "source": "GitHub tag",
                "url": None,
            }
    return None


def _fetch_json(url: str, timeout: int) -> object | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Lixet-Version-Check"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
        return None

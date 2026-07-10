# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Semantic version parsing and GitHub release reporting."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path

from utils.ui import UI

RELEASES_URL = "https://api.github.com/repos/behdadaliz/Lixet/releases?per_page=50"
MAX_METADATA_BYTES = 1024 * 1024
SEMVER_RE = re.compile(
    r"^(?:v)?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@total_ordering
@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        left = (self.major, self.minor, self.patch)
        right = (other.major, other.minor, other.patch)
        if left != right:
            return left < right
        if not self.prerelease:
            return False if not other.prerelease else False
        if not other.prerelease:
            return True
        for a, b in zip(self.prerelease, other.prerelease, strict=False):
            if a == b:
                continue
            a_num = a.isdigit()
            b_num = b.isdigit()
            if a_num and b_num:
                return int(a) < int(b)
            if a_num != b_num:
                return a_num
            return a < b
        return len(self.prerelease) < len(other.prerelease)


class VersionReporter:
    def __init__(self, no_color: bool = False) -> None:
        self.ui = UI(no_color=no_color)

    def run(self) -> bool:
        installed = read_installed_version()
        parsed = parse_version(installed)
        channel = "prerelease" if parsed and parsed.prerelease else "stable"
        latest = fetch_github_version(channel=channel)
        latest_version = str(latest.get("tag") or latest["version"]) if latest else "not available"
        status = _status(installed, latest_version, latest is not None)
        self.ui.banner("Lixet Version")
        self._line("Installed version", installed)
        self._line("Latest release", latest_version)
        self._line("Status", status)
        if latest and latest.get("url"):
            self._line("Release URL", str(latest["url"]))
        print()
        print(self.ui.c("Update command:", self.ui.BOLD + self.ui.CYAN))
        print(f"  {self.ui.c('sudo lixet --update', self.ui.BOLD)}")
        return True

    def _line(self, key: str, value: str) -> None:
        print(f"{self.ui.c(key.ljust(18), self.ui.BOLD + self.ui.CYAN)}: {self.ui.clean(value)}")


def parse_version(text: str) -> SemVer | None:
    match = SEMVER_RE.fullmatch(text.strip())
    if not match:
        return None
    prerelease = tuple(match.group("pre").split(".")) if match.group("pre") else ()
    build = tuple(match.group("build").split(".")) if match.group("build") else ()
    return SemVer(int(match.group("major")), int(match.group("minor")), int(match.group("patch")), prerelease, build)


def normalize_version(text: str) -> str | None:
    clean = text.strip()
    compact = re.fullmatch(
        r"v?(?P<core>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
        r"-(?P<stage>alpha|beta|rc)(?P<number>\d+)(?P<build>\+[0-9A-Za-z.-]+)?",
        clean,
        re.I,
    )
    if compact:
        build = compact.group("build") or ""
        return f"{compact.group('core')}-{compact.group('stage').lower()}.{int(compact.group('number'))}{build}"
    parsed = parse_version(clean)
    if parsed:
        return str(parsed)
    legacy = re.search(
        r"(?i)(?:(alpha|beta|rc)[_\s-]*)?v?(\d+)\.(\d+)\.(\d+)(?:[_\s-]*(alpha|beta|rc)(?:[._\s-]*(\d+))?)?",
        clean,
    )
    if not legacy:
        return None
    stage = (legacy.group(1) or legacy.group(5) or "").lower()
    number = legacy.group(6)
    value = f"{int(legacy.group(2))}.{int(legacy.group(3))}.{int(legacy.group(4))}"
    if stage:
        value += f"-{stage}"
        if number:
            value += f".{int(number)}"
    return value


def version_key(text: str) -> SemVer | None:
    normalized = normalize_version(text)
    return parse_version(normalized) if normalized else None


def read_installed_version(root: Path | None = None) -> str:
    base = root or Path(__file__).resolve().parents[1]
    try:
        raw = (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if parse_version(raw):
        return raw
    return normalize_version(raw) or raw or "unknown"


def fetch_github_version(timeout: int = 6, channel: str = "stable") -> dict | None:
    return select_latest_release(_fetch_json(RELEASES_URL, timeout), channel=channel)


def select_latest_release(items: object, channel: str | None = None) -> dict | None:
    if not isinstance(items, list):
        return None
    candidates: list[tuple[SemVer, str, dict]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info(item)
        if not info:
            continue
        version = version_key(info["version"])
        if version is None:
            continue
        if channel == "stable" and version.prerelease:
            continue
        # The prerelease channel may advance to a final release. Stable users
        # never receive a prerelease automatically.
        date = str(item.get("published_at") or item.get("created_at") or "")
        candidates.append((version, date, info))
    if not candidates:
        return None
    candidates.sort(key=lambda value: (value[0], value[1]))
    return candidates[-1][2]


def select_latest_tag(items: object) -> dict | None:
    if not isinstance(items, list):
        return None
    releases = [
        {"tag_name": item.get("name"), "name": item.get("name"), "html_url": None, "zipball_url": None}
        for item in items
        if isinstance(item, dict)
    ]
    return select_latest_release(releases)


def _release_info(item: dict) -> dict | None:
    tag = str(item.get("tag_name") or "").strip()
    version = normalize_version(tag)
    if not version:
        return None
    parsed = version_key(version)
    return {
        "version": version,
        "display": str(item.get("name") or tag),
        "url": item.get("html_url"),
        "tag": tag,
        "zipball_url": item.get("zipball_url"),
        "assets": item.get("assets") if isinstance(item.get("assets"), list) else [],
        "prerelease": bool(parsed and parsed.prerelease),
    }


def _fetch_json(url: str, timeout: int) -> object | None:
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Lixet-Version-Check", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            return None
        return json.loads(data.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeError, urllib.error.URLError, TimeoutError, OSError):
        return None


def _status(installed: str, latest: str, checked: bool) -> str:
    if not checked:
        return "unable to check"
    current = version_key(installed)
    target = version_key(latest)
    if current is None:
        return "installed version unknown"
    if target is None:
        return "unable to check"
    if current == target:
        return "up to date"
    if current < target:
        return "update available"
    return "newer than latest release"

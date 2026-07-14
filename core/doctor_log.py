# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Plain-text Doctor session logging."""

from __future__ import annotations

import os
import platform
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.layout import DEFAULT_LAYOUT
from core.version import read_installed_version
from utils.ui import UI


SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*\S+"
)
ANSI_RE = UI.CONTROL_RE


class DoctorLogWriter:
    def __init__(
        self,
        log_dir: str | Path | None = None,
        fallback_dir: str | Path | None = None,
        keep: int = 20,
    ) -> None:
        self.log_dir = Path(log_dir) if log_dir is not None else DEFAULT_LAYOUT.log_dir
        self.fallback_dir = Path(fallback_dir) if fallback_dir is not None else DEFAULT_LAYOUT.state_dir / "logs"
        self.keep = keep

    def write(self, session: dict) -> tuple[Path | None, str | None]:
        root, warning = self._prepare_dir(self.log_dir)
        if root is None:
            root, warning = self._prepare_dir(self.fallback_dir)
        if root is None:
            return None, warning or "No safe Doctor log directory is writable."
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = root / f"doctor-{stamp}.log"
        text = self._render(session)
        fd = -1
        tmp: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=root)
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                fd = -1
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            if os.name == "posix":
                tmp.chmod(0o600)
            os.replace(tmp, path)
            tmp = None
            if os.name == "posix":
                path.chmod(0o600)
            self._cleanup(root)
            return path, warning
        except OSError as exc:
            return None, f"Could not write Doctor log: {exc}"
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp and tmp.exists():
                tmp.unlink(missing_ok=True)

    def _prepare_dir(self, path: Path) -> tuple[Path | None, str | None]:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                return None, f"Unsafe Doctor log directory: {path}"
            if os.name == "posix":
                path.chmod(0o700)
            return path, None
        except OSError as exc:
            return None, f"Cannot prepare Doctor log directory {path}: {exc}"

    def _cleanup(self, root: Path) -> None:
        if self.keep <= 0:
            return
        logs = sorted(root.glob("doctor-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in logs[self.keep :]:
            try:
                if old.is_file() and not old.is_symlink():
                    old.unlink()
            except OSError:
                continue

    def _render(self, session: dict) -> str:
        now = datetime.now(timezone.utc).astimezone()
        lines = [
            "Lixet Doctor Log",
            "================",
            f"Lixet version: {read_installed_version()}",
            f"Timestamp: {now.isoformat()}",
            f"Timezone: {getattr(now.tzinfo, 'key', None) or now.tzname() or ZoneInfo('UTC').key}",
            f"Platform: {platform.platform()}",
            f"Python: {platform.python_version()}",
            "",
            "Summary",
            "-------",
        ]
        summary = session.get("summary") or {}
        for key in (
            "services_checked",
            "services_skipped",
            "errors",
            "warnings",
            "observations",
            "safe",
            "guarded",
            "report_only",
        ):
            lines.append(f"{key.replace('_', ' ').title()}: {summary.get(key, 0)}")
        lines.extend(["", "Services", "--------"])
        for result in session.get("results") or []:
            lines.append(f"{result.service}: {result.status}")
            if result.message:
                lines.append(f"  detail: {self._clean(result.message)}")
            validator = self._validator(result.data or {})
            lines.append(f"  native validator: {validator}")
        lines.extend(["", "Findings", "--------"])
        items = session.get("items") or []
        observations = session.get("observations") or []
        if not items and not observations:
            lines.append("No findings.")
        for service, item in items:
            self._finding(lines, service, item)
        if observations:
            lines.extend(["", "Informational Observations", "--------------------------"])
            for service, item in observations:
                self._finding(lines, service, item)
        lines.extend(["", "Repairs", "-------"])
        repairs = session.get("repairs") or []
        if not repairs:
            lines.append("No repairs attempted.")
        for item in repairs:
            lines.append(self._clean(str(item)))
        return "\n".join(self._clean(line) for line in lines) + "\n"

    def _finding(self, lines: list[str], service: str, item: dict) -> None:
        loc = f"{item.get('file_path') or '-'}"
        if item.get("line_number"):
            loc += f":{item['line_number']}"
        lines.append(f"- [{item.get('severity')}] {service} {item.get('code')}")
        lines.append(f"  location: {self._clean(loc)}")
        lines.append(f"  repairability: {item.get('repair_level')}")
        lines.append(f"  confidence: {item.get('confidence', 'high')}")
        if item.get("source_command"):
            lines.append(f"  command: {self._clean(str(item.get('source_command')))}")
        if item.get("evidence"):
            lines.append(f"  evidence: {self._clean(str(item.get('evidence')))}")

    @staticmethod
    def _validator(data: dict) -> str:
        for key in ("config_test", "findmnt_verify"):
            result = data.get(key)
            if result is None:
                continue
            timeout = " timeout" if result.get("timeout") else ""
            return f"{result.get('command', key)} exit={result.get('returncode')}{timeout}"
        return "not available"

    @staticmethod
    def _clean(text: str) -> str:
        text = ANSI_RE.sub("", str(text))
        text = SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
        return UI.clean(text)

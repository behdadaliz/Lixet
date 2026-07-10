# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic, snapshot-bound text repair operations."""

from __future__ import annotations

import codecs
import os
import tempfile
from pathlib import Path

from repair.snapshot import FileSnapshot, SnapshotError, capture_snapshot, require_unchanged


class RepairError(RuntimeError):
    """Raised when a deterministic repair cannot be applied."""


class RepairManager:
    """Preview and atomically apply exact text edits."""

    LINE_ACTIONS = {
        "replace",
        "replace_preserve_comment",
        "delete",
        "comment_out",
        "comment_out_with_reason",
        "insert_before",
        "insert_after",
        "append_token",
    }
    CONTENT_ACTIONS = {"append", "replace", "replace_preserve_comment", "insert_before", "insert_after"}

    @classmethod
    def preview_fixes(cls, file_path: str, fixes: list[dict], snapshot: FileSnapshot | None = None) -> list[str]:
        snap = snapshot or capture_snapshot(file_path)
        cls._ensure_path(snap, file_path)
        lines, _bom = cls._read_lines(Path(snap.resolved_path))
        return cls._apply_to_lines(lines, fixes)[1]

    @classmethod
    def apply_fixes(cls, file_path: str, fixes: list[dict], snapshot: FileSnapshot | None = None) -> bool:
        try:
            snap = snapshot or capture_snapshot(file_path)
            cls._ensure_path(snap, file_path)
            require_unchanged(snap)
            target = Path(snap.resolved_path)
            lines, bom = cls._read_lines(target)
            repaired, _messages = cls._apply_to_lines(lines, fixes)
            require_unchanged(snap)
            cls._atomic_write(target, bom + "".join(repaired).encode("utf-8"), snap)
            if snap.is_symlink and not Path(snap.original_path).is_symlink():
                raise RepairError(f"Symlink changed during repair: {snap.original_path}")
            return True
        except (OSError, UnicodeError, SnapshotError) as exc:
            if isinstance(exc, RepairError):
                raise
            raise RepairError(f"Failed to repair {file_path}: {exc}") from exc

    @classmethod
    def _apply_to_lines(cls, lines: list[str], fixes: list[dict]) -> tuple[list[str], list[str]]:
        clean = cls._normalize_fixes(fixes)
        result = list(lines)
        original_eof = lines[-1] if lines else ""
        messages: list[str] = []
        line_fixes = [fix for fix in clean if fix["action"] in cls.LINE_ACTIONS]
        line_fixes.sort(key=lambda fix: int(fix["line_number"]), reverse=True)

        for fix in line_fixes:
            action = str(fix["action"])
            line_number = int(fix["line_number"])
            index = line_number - 1
            if index < 0 or index >= len(result):
                raise RepairError(f"Line {line_number} is outside file bounds")
            expected = str(fix["expected_original"])
            if result[index] != expected:
                raise RepairError(f"Line {line_number} changed after inspection")

            original = result[index]
            ending = cls._ending(original)
            if action == "replace":
                content = str(fix["content"]).rstrip("\r\n") + ending
                messages.append(f"replace line {line_number}: {original.rstrip()} -> {content.rstrip()}")
                result[index] = content
            elif action == "replace_preserve_comment":
                content = cls._replace_preserve_comment(original, str(fix["content"]))
                messages.append(f"replace line {line_number}: {original.rstrip()} -> {content.rstrip()}")
                result[index] = content
            elif action == "delete":
                messages.append(f"delete line {line_number}: {original.rstrip()}")
                del result[index]
            elif action in {"comment_out", "comment_out_with_reason"}:
                reason = str(fix.get("reason") or "Lixet disabled")
                content = cls._comment_line(original, reason)
                messages.append(f"comment line {line_number}: {original.rstrip()} -> {content.rstrip()}")
                result[index] = content
            elif action == "insert_before":
                content = str(fix["content"]).rstrip("\r\n") + ending
                messages.append(f"insert before line {line_number}: {content.rstrip()}")
                result.insert(index, content)
            elif action == "insert_after":
                content = str(fix["content"]).rstrip("\r\n") + ending
                messages.append(f"insert after line {line_number}: {content.rstrip()}")
                result.insert(index + 1, content)
            elif action == "append_token":
                content = cls._append_token(original, str(fix["token"]))
                messages.append(f"append token on line {line_number}: {fix['token']}")
                result[index] = content

        for fix in [item for item in clean if item["action"] == "append"]:
            expected_eof = str(fix["expected_eof"])
            if original_eof != expected_eof:
                raise RepairError("File ending changed after inspection")
            ending = cls._file_ending(lines)
            normalized = str(fix["content"]).rstrip("\r\n").replace("\r\n", "\n").replace("\r", "\n")
            content = normalized.replace("\n", ending) + ending
            messages.append(f"append: {content.rstrip()}")
            if result and not result[-1].endswith(("\n", "\r")):
                result[-1] += ending
            result.append(content)

        return result, messages

    @classmethod
    def _normalize_fixes(cls, fixes: list[dict]) -> list[dict]:
        clean: list[dict] = []
        seen: dict[int, str] = {}
        supported = cls.LINE_ACTIONS | {"append"}

        for fix in fixes:
            action = fix.get("action")
            if action not in supported:
                raise RepairError(f"Unsupported repair action: {action}")
            item: dict = {"action": action}

            if action in cls.LINE_ACTIONS:
                try:
                    line_number = int(fix["line_number"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RepairError(f"Invalid line number for {action} repair") from exc
                if "expected_original" not in fix:
                    raise RepairError(f"Missing expected original content for line {line_number}")
                if action not in {"insert_before", "insert_after"} and line_number in seen:
                    raise RepairError(f"Conflicting repairs for line {line_number}: {seen[line_number]} and {action}")
                if action not in {"insert_before", "insert_after"}:
                    seen[line_number] = str(action)
                item["line_number"] = line_number
                item["expected_original"] = str(fix["expected_original"])

            if action in cls.CONTENT_ACTIONS:
                if "content" not in fix:
                    raise RepairError(f"Missing content for {action} repair")
                item["content"] = str(fix["content"])
            if action == "append":
                if "expected_eof" not in fix:
                    raise RepairError("Missing expected file ending for append repair")
                item["expected_eof"] = str(fix["expected_eof"])
            if action == "append_token":
                if not str(fix.get("token") or "").strip():
                    raise RepairError("Missing token for append_token repair")
                item["token"] = str(fix["token"]).strip()
            if action == "comment_out_with_reason":
                item["reason"] = str(fix.get("reason") or "Lixet disabled")
            clean.append(item)
        return clean

    @staticmethod
    def _read_lines(path: Path) -> tuple[list[str], bytes]:
        data = path.read_bytes()
        bom = codecs.BOM_UTF8 if data.startswith(codecs.BOM_UTF8) else b""
        if bom:
            data = data[len(bom) :]
        return data.decode("utf-8").splitlines(keepends=True), bom

    @staticmethod
    def _atomic_write(path: Path, content: bytes, snapshot: FileSnapshot) -> None:
        fd = -1
        tmp: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".lixet.tmp", dir=path.parent)
            tmp = Path(tmp_name)
            with os.fdopen(fd, "wb", closefd=True) as out:
                fd = -1
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
                if hasattr(os, "fchmod"):
                    os.fchmod(out.fileno(), snapshot.mode)
                if hasattr(os, "fchown"):
                    try:
                        os.fchown(out.fileno(), snapshot.uid, snapshot.gid)
                    except PermissionError:
                        current = os.fstat(out.fileno())
                        if (getattr(current, "st_uid", 0), getattr(current, "st_gid", 0)) != (
                            snapshot.uid,
                            snapshot.gid,
                        ):
                            raise
            if not hasattr(os, "fchmod"):
                tmp.chmod(snapshot.mode)
            os.replace(tmp, path)
            tmp = None
            RepairManager._fsync_dir(path.parent)
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp and tmp.exists():
                tmp.unlink(missing_ok=True)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _ensure_path(snapshot: FileSnapshot, file_path: str) -> None:
        if Path(snapshot.original_path) != Path(file_path).absolute():
            raise RepairError("Snapshot does not belong to the requested file")

    @staticmethod
    def _ending(line: str) -> str:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
        if line.endswith("\r"):
            return "\r"
        return "\n"

    @staticmethod
    def _file_ending(lines: list[str]) -> str:
        for line in reversed(lines):
            if line.endswith("\r\n"):
                return "\r\n"
            if line.endswith("\n"):
                return "\n"
            if line.endswith("\r"):
                return "\r"
        return "\n"

    @staticmethod
    def _comment_line(line: str, reason: str) -> str:
        ending = RepairManager._ending(line) if line.endswith(("\n", "\r")) else ""
        body = line[: -len(ending)] if ending else line
        indent = body[: len(body) - len(body.lstrip())]
        return f"{indent}# {reason}: {body.lstrip()}".rstrip() + ending

    @staticmethod
    def _replace_preserve_comment(line: str, content: str) -> str:
        ending = RepairManager._ending(line) if line.endswith(("\n", "\r")) else ""
        body = line[: -len(ending)] if ending else line
        indent = body[: len(body) - len(body.lstrip())]
        new_body = indent + content.strip()
        if "#" not in body:
            return new_body + ending
        _left, comment = body.split("#", 1)
        return f"{new_body} # {comment.strip()}".rstrip() + ending

    @staticmethod
    def _append_token(line: str, token: str) -> str:
        ending = RepairManager._ending(line) if line.endswith(("\n", "\r")) else ""
        body = line[: -len(ending)] if ending else line
        if "#" in body:
            left, comment = body.split("#", 1)
            return f"{left.rstrip()} {token} # {comment.strip()}".rstrip() + ending
        return f"{body.rstrip()} {token}" + ending

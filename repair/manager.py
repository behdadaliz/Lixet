# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic, line-oriented repair operations."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class RepairError(RuntimeError):
    """Raised when a deterministic repair cannot be applied."""


class RepairManager:
    """Apply validated fixes to text configuration files."""

    @staticmethod
    def preview_fixes(file_path: str, fixes: list[dict]) -> list[str]:
        lines = Path(file_path).read_text(encoding="utf-8-sig").splitlines(keepends=True)
        return RepairManager._apply_to_lines(lines, fixes, preview=True)[1]

    @staticmethod
    def apply_fixes(file_path: str, fixes: list[dict]) -> bool:
        path = Path(file_path)
        tmp: Path | None = None
        try:
            original = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
            repaired, _ = RepairManager._apply_to_lines(original, fixes, preview=False)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".lixet.tmp", dir=path.parent)
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
                out.write("".join(repaired))
            shutil.copystat(path, tmp)
            os.replace(tmp, path)
            return True
        except OSError as exc:
            raise RepairError(f"Failed to repair {file_path}: {exc}") from exc
        finally:
            if tmp and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _apply_to_lines(lines: list[str], fixes: list[dict], preview: bool) -> tuple[list[str], list[str]]:
        fixes = RepairManager._normalize_fixes(fixes)
        result = list(lines)
        messages: list[str] = []
        line_fixes = [
            fix for fix in fixes
            if fix.get("action") in {
                "replace",
                "replace_preserve_comment",
                "delete",
                "comment_out",
                "comment_out_with_reason",
                "insert_before",
                "insert_after",
            }
        ]
        line_fixes.sort(key=lambda fix: int(fix["line_number"]), reverse=True)

        for fix in line_fixes:
            action = fix["action"]
            line_number = int(fix["line_number"])
            index = line_number - 1
            if index < 0 or index >= len(result):
                raise RepairError(f"Line {line_number} is outside file bounds")
            if action == "replace":
                content = str(fix["content"]).rstrip("\n") + "\n"
                messages.append(f"replace line {line_number}: {result[index].rstrip()} -> {content.rstrip()}")
                if not preview:
                    result[index] = content
            elif action == "replace_preserve_comment":
                content = RepairManager._replace_preserve_comment(result[index], str(fix["content"]))
                messages.append(f"replace line {line_number}: {result[index].rstrip()} -> {content.rstrip()}")
                if not preview:
                    result[index] = content
            elif action == "delete":
                messages.append(f"delete line {line_number}: {result[index].rstrip()}")
                if not preview:
                    del result[index]
            elif action in {"comment_out", "comment_out_with_reason"}:
                reason = str(fix.get("reason") or "Lixet disabled")
                content = RepairManager._comment_line(result[index], reason)
                messages.append(f"comment line {line_number}: {result[index].rstrip()} -> {content.rstrip()}")
                if not preview:
                    result[index] = content
            elif action == "insert_before":
                content = str(fix["content"]).rstrip("\n") + "\n"
                messages.append(f"insert before line {line_number}: {content.rstrip()}")
                if not preview:
                    result.insert(index, content)
            elif action == "insert_after":
                content = str(fix["content"]).rstrip("\n") + "\n"
                messages.append(f"insert after line {line_number}: {content.rstrip()}")
                if not preview:
                    result.insert(index + 1, content)

        for fix in [fix for fix in fixes if fix.get("action") == "append"]:
            content = str(fix["content"]).rstrip("\n") + "\n"
            messages.append(f"append: {content.rstrip()}")
            if not preview:
                if result and not result[-1].endswith("\n"):
                    result[-1] += "\n"
                result.append(content)

        return result, messages

    @staticmethod
    def _normalize_fixes(fixes: list[dict]) -> list[dict]:
        clean: list[dict] = []
        seen: dict[int, str] = {}

        for fix in fixes:
            action = fix.get("action")
            if action not in {
                "append",
                "replace",
                "replace_preserve_comment",
                "delete",
                "comment_out",
                "comment_out_with_reason",
                "insert_before",
                "insert_after",
            }:
                raise RepairError(f"Unsupported repair action: {action}")

            item = {"action": action}
            if action in {
                "replace",
                "replace_preserve_comment",
                "delete",
                "comment_out",
                "comment_out_with_reason",
                "insert_before",
                "insert_after",
            }:
                try:
                    line_number = int(fix["line_number"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RepairError(f"Invalid line number for {action} repair") from exc
                if action in {"replace", "replace_preserve_comment", "delete", "comment_out", "comment_out_with_reason"} and line_number in seen:
                    raise RepairError(f"Conflicting repairs for line {line_number}: {seen[line_number]} and {action}")
                if action in {"replace", "replace_preserve_comment", "delete", "comment_out", "comment_out_with_reason"}:
                    seen[line_number] = action
                item["line_number"] = line_number

            if action in {"append", "replace", "replace_preserve_comment", "insert_before", "insert_after"}:
                if "content" not in fix:
                    raise RepairError(f"Missing content for {action} repair")
                item["content"] = str(fix["content"])

            if action == "comment_out_with_reason":
                item["reason"] = str(fix.get("reason") or "Lixet disabled")

            clean.append(item)

        return clean

    @staticmethod
    def _comment_line(line: str, reason: str) -> str:
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        return f"# {reason}: {body.lstrip()}".rstrip() + ending

    @staticmethod
    def _replace_preserve_comment(line: str, content: str) -> str:
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        new_body = content.rstrip("\n")
        if "#" not in body:
            return new_body + ending
        _, comment = body.split("#", 1)
        return f"{new_body} # {comment.strip()}".rstrip() + ending

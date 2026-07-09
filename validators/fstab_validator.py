# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic fstab validator."""

from __future__ import annotations

from validators.helpers import issue


class FstabValidator:
    def __init__(self, file_path: str = "/etc/fstab") -> None:
        self.file_path = file_path

    def run_rules(self, data: dict) -> list[dict]:
        rows = data["lines"]
        issues: list[dict] = []
        active = [row for row in rows if row["is_active"]]
        if not active:
            issues.append(issue("FSTAB_EMPTY", "high", "fstab has no active entries.", self.file_path, [], None, "fstab", None, "No automatic repair is available.", None, "unsafe"))
            return issues

        verify = data.get("findmnt_verify")
        if verify and verify["returncode"] != 0:
            issues.append(issue(
                "FSTAB_VERIFY_FAILED",
                "high",
                "findmnt reports fstab validation problems.",
                self.file_path,
                [],
                None,
                "fstab",
                verify.get("evidence") or "findmnt validation failed.",
                "No automatic repair is applied from command output alone.",
                verify.get("command"),
                "unsafe",
            ))

        seen_mounts: set[str] = set()
        for row in active:
            parts = row["text"].split()
            if len(parts) < 4:
                issues.append(issue(
                    "FSTAB_MISSING_FIELDS",
                    "high",
                    "fstab entry has fewer than four required fields.",
                    self.file_path,
                    [],
                    row["line_number"],
                    "fstab",
                    row["text"],
                    "No automatic repair is available for incomplete mount entries.",
                    None,
                    "unsafe",
                ))
                continue
            mountpoint = parts[1]
            if mountpoint in seen_mounts:
                issues.append(issue(
                    "FSTAB_DUPLICATE_MOUNTPOINT",
                    "medium",
                    f"Duplicate fstab mountpoint '{mountpoint}'.",
                    self.file_path,
                    [{"action": "comment_out_with_reason", "line_number": row["line_number"], "reason": "Lixet disabled duplicate fstab mountpoint"}],
                    row["line_number"],
                    "fstab",
                    row["text"],
                    "Duplicate mountpoints can be commented only after review.",
                    None,
                    "guarded",
                    "Commenting a mount entry can affect boot-time mounts.",
                ))
            else:
                seen_mounts.add(mountpoint)

            fixed = list(parts)
            bad_fields = []
            if len(parts) >= 5 and parts[4] not in {"0", "1"}:
                fixed[4] = "0"
                bad_fields.append("dump")
            if len(parts) >= 6 and parts[5] not in {"0", "1", "2"}:
                fixed[5] = "0"
                bad_fields.append("pass")
            if bad_fields:
                issues.append(issue(
                    "FSTAB_INVALID_NUMERIC_FIELDS",
                    "medium",
                    f"Invalid fstab numeric field(s): {', '.join(bad_fields)}.",
                    self.file_path,
                    [{"action": "replace", "line_number": row["line_number"], "content": "\t".join(fixed)}],
                    row["line_number"],
                    "fstab",
                    row["text"],
                    "Invalid numeric fields can be replaced with 0 after review.",
                    None,
                    "guarded",
                    "Changing fstab fields can affect boot or mount behavior.",
                ))
        return issues

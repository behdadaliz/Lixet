# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Shared typed models for diagnosis, repair, and CLI results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import TypedDict


class ExitCode(IntEnum):
    OK = 0
    ISSUES = 1
    USAGE = 2
    INSPECTION_FAILED = 3
    REPAIR_FAILED = 4
    ROLLBACK_FAILED = 5


class RepairLevel(str, Enum):
    SAFE = "safe"
    GUARDED = "guarded"
    REPORT_ONLY = "unsafe"


class VerificationState(str, Enum):
    VERIFIED = "verified"
    INTERNALLY_VERIFIED = "internally verified"
    EXTERNAL_UNAVAILABLE = "external verifier unavailable"
    FAILED = "verification failed"
    ROLLBACK_FAILED = "rollback failed"


class RepairAction(TypedDict, total=False):
    action: str
    line_number: int
    content: str
    token: str
    reason: str
    expected_original: str
    expected_eof: str


class Issue(TypedDict, total=False):
    id: str
    code: str
    severity: str
    service: str | None
    description: str
    file_path: str
    line_number: int | None
    evidence: str | None
    repairable: bool
    repair_level: str
    safety_note: str | None
    risk_note: str | None
    rollback_note: str | None
    source_command: str | None
    fixes: list[RepairAction]
    resolved_path: str
    symlink_target: str


@dataclass(frozen=True)
class VerificationResult:
    state: VerificationState
    message: str

    @property
    def successful(self) -> bool:
        return self.state in {VerificationState.VERIFIED, VerificationState.INTERNALLY_VERIFIED}

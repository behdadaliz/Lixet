# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Deterministic target detection for future path-based scans."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from core.registry import ServiceSpec, iter_services
from utils.ui import UI


class DetectionStatus(str, Enum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass(frozen=True)
class DetectionEvidence:
    kind: str
    detail: str
    weight: int


@dataclass(frozen=True)
class DetectionCandidate:
    service: str
    score: int
    evidence: tuple[DetectionEvidence, ...]


@dataclass(frozen=True)
class DetectionResult:
    status: DetectionStatus
    path: str
    target_type: str | None
    candidates: tuple[DetectionCandidate, ...]
    message: str = ""
    binary: bool = False
    truncated: bool = False

    @property
    def best(self) -> DetectionCandidate | None:
        return self.candidates[0] if self.status == DetectionStatus.MATCH else None


class TargetDetector:
    MAX_READ = 8192

    def __init__(self, services: tuple[ServiceSpec, ...] | None = None, max_read: int = MAX_READ) -> None:
        self.services = services or iter_services()
        self.max_read = max_read
        self._order = {item.name: index for index, item in enumerate(self.services)}

    def detect(self, target: str | Path) -> DetectionResult:
        path = Path(target)
        display = str(path)
        try:
            link_stat = path.lstat()
        except OSError as exc:
            return DetectionResult(DetectionStatus.ERROR, display, None, (), UI.clean(str(exc)))

        try:
            if stat.S_ISLNK(link_stat.st_mode):
                resolved = path.resolve(strict=True)
                target_stat = resolved.stat()
            else:
                resolved = path
                target_stat = path.stat()
        except (OSError, RuntimeError) as exc:
            return DetectionResult(DetectionStatus.ERROR, display, None, (), f"Cannot resolve target: {UI.clean(str(exc))}")

        if stat.S_ISDIR(target_stat.st_mode):
            target_type = "directory"
            content = None
            binary = False
            truncated = False
        elif stat.S_ISREG(target_stat.st_mode):
            target_type = "file"
            try:
                content_bytes = self._read_prefix(resolved)
            except OSError as exc:
                return DetectionResult(
                    DetectionStatus.ERROR,
                    display,
                    "file",
                    (),
                    f"Cannot read target: {UI.clean(str(exc))}",
                )
            binary = self._looks_binary(content_bytes)
            truncated = target_stat.st_size > len(content_bytes)
            content = None if binary else content_bytes.decode("utf-8", errors="replace").lower()
        else:
            return DetectionResult(DetectionStatus.UNKNOWN, display, None, (), "Target is not a file or directory.")

        candidates = self._candidates(path, target_type, content)
        if not candidates:
            message = "Target looks binary." if binary else "No registered service matched this target."
            return DetectionResult(DetectionStatus.UNKNOWN, display, target_type, (), message, binary, truncated)
        if all(all(evidence.kind == "content" for evidence in item.evidence) for item in candidates):
            if len(candidates) > 1 and candidates[0].score == candidates[1].score:
                return DetectionResult(
                    DetectionStatus.AMBIGUOUS,
                    display,
                    target_type,
                    tuple(candidates),
                    "Only weak content signatures matched.",
                    binary,
                    truncated,
                )
            return DetectionResult(
                DetectionStatus.UNKNOWN,
                display,
                target_type,
                tuple(candidates),
                "Only weak content signatures matched.",
                binary,
                truncated,
            )
        if len(candidates) > 1 and candidates[0].score == candidates[1].score:
            return DetectionResult(DetectionStatus.AMBIGUOUS, display, target_type, tuple(candidates), "", binary, truncated)
        return DetectionResult(DetectionStatus.MATCH, display, target_type, tuple(candidates), "", binary, truncated)

    def _candidates(
        self,
        path: Path,
        target_type: str,
        content: str | None,
    ) -> list[DetectionCandidate]:
        result: list[DetectionCandidate] = []
        posix = _posix(path)
        pure = PurePosixPath(posix)
        for spec in self.services:
            evidence: list[DetectionEvidence] = []
            if target_type not in spec.accepted_target_types:
                continue
            if any(_same_or_suffix(posix, known) for known in spec.known_paths):
                evidence.append(DetectionEvidence("exact_path", posix, 100))
            if spec.matches_filename(path.name):
                evidence.append(DetectionEvidence("filename", path.name, 40))
            if spec.matches_parent(pure):
                evidence.append(DetectionEvidence("parent", str(pure.parent), 35))
            if content:
                for signature in spec.detection_signatures:
                    if signature.text.lower() in content:
                        evidence.append(DetectionEvidence("content", signature.text, signature.weight))
            if evidence:
                score = sum(item.weight for item in evidence)
                result.append(DetectionCandidate(spec.name, score, tuple(evidence)))
        result.sort(key=lambda item: (-item.score, self._order[item.service], item.service))
        return result

    def _read_prefix(self, path: Path) -> bytes:
        with path.open("rb") as handle:
            return handle.read(self.max_read)

    @staticmethod
    def _looks_binary(data: bytes) -> bool:
        if b"\x00" in data:
            return True
        if not data:
            return False
        control = sum(1 for byte in data if byte < 32 and byte not in {9, 10, 13})
        return control / len(data) > 0.30


def detect_target(target: str | Path) -> DetectionResult:
    return TargetDetector().detect(target)


def _posix(path: Path) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()


def _same_or_suffix(path: str, known: str) -> bool:
    clean = PurePosixPath(path).as_posix().rstrip("/")
    target = PurePosixPath(known).as_posix().rstrip("/")
    return clean == target or clean.endswith(target)

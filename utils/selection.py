# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Reusable parser for interactive issue selections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SelectionAction(str, Enum):
    SELECT = "select"
    ALL = "all"
    RESCAN = "rescan"
    QUIT = "quit"
    EMPTY = "empty"
    INVALID = "invalid"


@dataclass(frozen=True)
class SelectionResult:
    action: SelectionAction
    indexes: tuple[int, ...] = ()
    error: str = ""

    @property
    def valid(self) -> bool:
        return self.action != SelectionAction.INVALID


def parse_selection(text: str, total: int) -> SelectionResult:
    raw = text.strip().lower()
    if not raw:
        return SelectionResult(SelectionAction.EMPTY)
    if raw == "a":
        return SelectionResult(SelectionAction.ALL)
    if raw == "r":
        return SelectionResult(SelectionAction.RESCAN)
    if raw == "q":
        return SelectionResult(SelectionAction.QUIT)
    if total < 1:
        return SelectionResult(SelectionAction.INVALID, error="There are no issues to select.")

    selected: list[int] = []
    seen: set[int] = set()
    for part in [item.strip() for item in raw.split(",")]:
        if not part:
            return SelectionResult(SelectionAction.INVALID, error="Empty selection item.")
        values = _range(part) if "-" in part else _number(part)
        if isinstance(values, str):
            return SelectionResult(SelectionAction.INVALID, error=values)
        for value in values:
            if value < 1:
                return SelectionResult(SelectionAction.INVALID, error="Selection indexes start at 1.")
            if value > total:
                return SelectionResult(SelectionAction.INVALID, error=f"Selection {value} is outside the issue list.")
            if value not in seen:
                seen.add(value)
                selected.append(value)
    return SelectionResult(SelectionAction.SELECT, tuple(selected))


def _number(text: str) -> list[int] | str:
    if not text.isdecimal():
        return f"Invalid selection '{text}'."
    return [int(text)]


def _range(text: str) -> list[int] | str:
    if text.count("-") != 1:
        return f"Malformed range '{text}'."
    left, right = [item.strip() for item in text.split("-", 1)]
    if not left.isdecimal() or not right.isdecimal():
        return f"Malformed range '{text}'."
    start = int(left)
    end = int(right)
    if end < start:
        return f"Reversed range '{text}' is not accepted."
    return list(range(start, end + 1))

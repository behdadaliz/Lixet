# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Terminal UI helpers for Lixet."""

from __future__ import annotations

import os
import sys
from textwrap import wrap


class UI:
    """Small dependency-free terminal formatter."""

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GRAY = "\033[90m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

    def __init__(self, no_color: bool = False) -> None:
        self.color = False if no_color else self._supports_color()

    def banner(self, title: str, subtitle: str | None = None) -> None:
        print()
        print(self.c(f"== {title} ==", self.BOLD + self.CYAN))
        if subtitle:
            print(self.c(subtitle, self.DIM))
        print()

    def section(self, title: str) -> None:
        print()
        print(self.c(title, self.BOLD + self.CYAN))
        print(self.c("-" * len(title), self.BLUE))

    def status(self, kind: str, message: str) -> None:
        colors = {
            "ok": self.GREEN,
            "warn": self.YELLOW,
            "error": self.RED,
            "critical": self.BOLD + self.RED,
            "high": self.RED,
            "medium": self.YELLOW,
            "low": self.CYAN,
            "info": self.CYAN,
            "skip": self.CYAN,
        }
        labels = {
            "ok": "OK",
            "warn": "WARN",
            "error": "ERR",
            "critical": "CRITICAL",
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
            "info": "INFO",
            "skip": "SKIP",
        }
        label = self.c(f"[{labels.get(kind, kind.upper())}]", colors.get(kind, ""))
        print(f"{label} {self.c(message, colors.get(kind, ''))}")

    def issue(self, idx: int | None, service: str, item: dict) -> None:
        sev = str(item.get("severity", "info")).lower()
        label = self.severity(sev)
        if idx is None:
            head = f"{label} {service + ' - ' if service else ''}{self.c(item['code'], self.BOLD)}"
        else:
            head = f"{self.c(str(idx) + '.', self.BOLD)} {label} {self.c(service, self.BOLD)} - {self.c(item['code'], self.BOLD)}"
        print(head)
        self.kv("Problem", item["description"])
        self.kv("Location", self.location(item))
        if item.get("source_command"):
            self.kv("Command", str(item["source_command"]))
        if item.get("evidence"):
            self.evidence(str(item["evidence"]))
        if item.get("fixes"):
            self.kv("Repair level", str(item.get("repair_level", "safe")))
            self.kv("Repair", self.repair_text(item))
        else:
            self.kv("Repair", item.get("safety_note") or "No safe automatic repair available.")
        if item.get("risk_note"):
            self.kv("Risk", str(item["risk_note"]))
        if item.get("rollback_note"):
            self.kv("Rollback", str(item["rollback_note"]))

    def kv(self, key: str, value: str) -> None:
        print(f"  {self.c((key + ':').ljust(12), self.BOLD + self.CYAN)} {value}")

    def bullet(self, text: str) -> None:
        lines = wrap(text, width=88, subsequent_indent="      ") or [text]
        print(f"  {self.c('-', self.CYAN)} {lines[0]}")
        for line in lines[1:]:
            print(line)

    def evidence(self, text: str) -> None:
        print(f"  {self.c('Evidence:', self.BOLD)}")
        for line in text.strip().splitlines():
            print(f"    {self.c(line, self.GRAY)}")

    def prompt(self, text: str) -> str:
        return input(self.c(text, self.BOLD))

    def severity(self, severity: str) -> str:
        colors = {
            "critical": self.BOLD + self.RED,
            "high": self.RED,
            "medium": self.YELLOW,
            "low": self.CYAN,
            "info": self.GRAY,
        }
        return self.c(f"[{severity.upper()}]", colors.get(severity, ""))

    @staticmethod
    def repair_text(item: dict) -> str:
        fixes = item.get("fixes") or []
        if not fixes:
            return "No safe automatic repair available."
        first = fixes[0]
        action = first.get("action", "repair")
        content = first.get("content")
        if content:
            return f"{action} {content!r}"
        return action

    def c(self, text: str, code: str) -> str:
        if not self.color or not code:
            return text
        return f"{code}{text}{self.RESET}"

    @staticmethod
    def location(item: dict) -> str:
        line = f":{item['line_number']}" if item.get("line_number") else ""
        return f"{item['file_path']}{line}"

    @staticmethod
    def _supports_color() -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        return sys.stdout.isatty()

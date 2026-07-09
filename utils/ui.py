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
    RESET = "\033[0m"

    def __init__(self) -> None:
        self.color = self._supports_color()

    def banner(self, title: str, subtitle: str | None = None) -> None:
        print()
        print(self.c(f"== {title} ==", self.BOLD))
        if subtitle:
            print(self.c(subtitle, self.DIM))
        print()

    def section(self, title: str) -> None:
        print()
        print(self.c(title, self.BOLD))
        print(self.c("-" * len(title), self.DIM))

    def status(self, kind: str, message: str) -> None:
        colors = {
            "ok": self.GREEN,
            "warn": self.YELLOW,
            "error": self.RED,
            "info": self.CYAN,
            "skip": self.CYAN,
        }
        labels = {
            "ok": "OK",
            "warn": "WARN",
            "error": "ERR",
            "info": "INFO",
            "skip": "SKIP",
        }
        label = self.c(f"[{labels.get(kind, kind.upper())}]", colors.get(kind, ""))
        print(f"{label} {message}")

    def issue(self, idx: int | None, service: str, item: dict) -> None:
        if idx is None:
            head = f"{service + ': ' if service else ''}{item['severity']} {item['code']}"
        else:
            head = f"{idx}. {service}: {item['severity']} {item['code']}"
        print(self.c(head, self.YELLOW if item["severity"] in {"high", "medium"} else self.CYAN))
        self.kv("Problem", item["description"])
        self.kv("Location", self.location(item))
        if item.get("evidence"):
            self.evidence(str(item["evidence"]))

    def kv(self, key: str, value: str) -> None:
        print(f"  {self.c(key + ':', self.BOLD)} {value}")

    def bullet(self, text: str) -> None:
        lines = wrap(text, width=88, subsequent_indent="      ") or [text]
        print(f"  - {lines[0]}")
        for line in lines[1:]:
            print(line)

    def evidence(self, text: str) -> None:
        print(f"  {self.c('Evidence:', self.BOLD)}")
        for line in text.strip().splitlines():
            print(f"    {line}")

    def prompt(self, text: str) -> str:
        return input(self.c(text, self.BOLD))

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
        return sys.stdout.isatty() or os.environ.get("TERM") not in {None, "", "dumb"}

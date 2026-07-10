# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""sysctl configuration discovery with procps load precedence."""

from __future__ import annotations

from pathlib import Path

from services.text_service import TextFileService


class SysctlService:
    DIRS = (
        "etc/sysctl.d",
        "run/sysctl.d",
        "usr/local/lib/sysctl.d",
        "usr/lib/sysctl.d",
        "lib/sysctl.d",
    )

    def __init__(self, config_path: str = "/etc/sysctl.conf", **_kwargs) -> None:
        self.config_path = config_path

    def inspect(self) -> dict:
        main = Path(self.config_path)
        if main.name == "sysctl.conf" and main.parent.name == "etc":
            files = self._system_files(main.parent.parent)
        else:
            if not main.exists():
                raise FileNotFoundError(f"sysctl configuration not found: {self.config_path}")
            files = [main]

        loaded = []
        for order, path in enumerate(files, start=1):
            info = TextFileService(str(path)).inspect()
            loaded.append(
                {
                    "file_path": str(path),
                    "load_order": order,
                    "lines": info["lines"],
                    "snapshot": info["snapshot"],
                }
            )
        return {"file_path": str(main), "files": loaded, "missing_config": not bool(loaded)}

    def _system_files(self, root: Path) -> list[Path]:
        selected: dict[str, Path] = {}
        for relative in self.DIRS:
            directory = root / relative
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.conf")):
                if path.name not in selected and path.is_file():
                    selected[path.name] = path
        ordered = [selected[name] for name in sorted(selected)]
        main = root / "etc" / "sysctl.conf"
        if main.is_file():
            ordered.append(main)
        return ordered

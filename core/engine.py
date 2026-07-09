# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Core orchestration for Lixet scans and repairs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from backup.manager import BackupError, BackupManager
from repair.manager import RepairError, RepairManager
from services.dns_service import DNSService
from services.networking_service import NetworkingService
from services.nginx_service import NginxService
from services.ssh_service import SSHService
from services.systemd_service import SystemdService
from services.ufw_service import UFWService
from validators.dns_validator import DNSValidator
from validators.networking_validator import NetworkingValidator
from validators.nginx_validator import NginxValidator
from validators.ssh_validator import SSHValidator
from validators.systemd_validator import SystemdValidator
from validators.ufw_validator import UFWValidator
from utils.ui import UI


class LixetEngine:
    """Run the deterministic Inspection -> Validation -> Backup -> Repair workflow."""

    def __init__(self, dry_run: bool = False, yes: bool = False, config_path: str | None = None) -> None:
        self.dry_run = dry_run
        self.yes = yes
        self.config_path = config_path
        self.backup_manager = BackupManager()
        self.repair_manager = RepairManager()
        self.ui = UI()
        self.supported_services = {
            "ssh": {
                "service": SSHService,
                "validator": SSHValidator,
                "default": "/etc/ssh/sshd_config",
                "verify": self._verify_ssh,
            },
            "nginx": {
                "service": NginxService,
                "validator": NginxValidator,
                "default": "/etc/nginx/nginx.conf",
                "verify": self._verify_nginx,
            },
            "ufw": {
                "service": UFWService,
                "validator": UFWValidator,
                "default": "/etc/ufw/ufw.conf",
                "verify": self._verify_true,
            },
            "dns": {
                "service": DNSService,
                "validator": DNSValidator,
                "default": "/etc/resolv.conf",
                "verify": self._verify_true,
            },
            "networking": {
                "service": NetworkingService,
                "validator": NetworkingValidator,
                "default": "/etc/hosts",
                "verify": self._verify_true,
            },
            "systemd": {
                "service": SystemdService,
                "validator": SystemdValidator,
                "default": "/etc/systemd/system",
                "verify": self._verify_systemd,
            },
        }
        if self.dry_run:
            self.ui.status("warn", "Dry run enabled. No files will be modified.")

    def scan_service(self, service_name: str) -> bool:
        service_name = service_name.lower()
        self.ui.banner(f"Scanning {service_name}", "Deterministic configuration inspection")
        if service_name not in self.supported_services:
            self.ui.status("error", f"Service '{service_name}' is not supported yet.")
            return False

        issues = self._collect_issues(service_name)
        if issues is None:
            return False

        if not issues:
            self.ui.status("ok", f"No issues detected in {service_name}.")
            return True

        self._print_issues(service_name, issues)
        return self._handle_issues(service_name, issues)

    def run_doctor(self) -> bool:
        self.ui.banner("Lixet Doctor", "Scanning supported services")
        items: list[tuple[str, dict]] = []
        for service_name in self.supported_services:
            issues = self._collect_issues(service_name, skip_missing=True)
            if issues:
                items.extend((service_name, item) for item in issues)

        self.ui.section("Doctor Summary")
        if not items:
            self.ui.status("ok", "No issues detected in supported services.")
            return True

        for idx, (service_name, item) in enumerate(items, start=1):
            self.ui.issue(idx, service_name, item)

        if self.yes:
            return self._repair_grouped(items)

        if self.dry_run:
            return self._preview_grouped(items)

        choice = self.ui.prompt("\nChoose a problem number, 'a' for all repairable, or Enter to abort: ").strip().lower()
        if not choice:
            self.ui.status("info", "Doctor repair aborted by user.")
            return False
        if choice == "a":
            return self._repair_grouped(items)
        try:
            selected = items[int(choice) - 1]
        except (ValueError, IndexError):
            self.ui.status("error", "Invalid selection.")
            return False
        return self._handle_issues(selected[0], [selected[1]])

    def _collect_issues(self, service_name: str, skip_missing: bool = False) -> list[dict] | None:
        spec = self.supported_services[service_name]
        config_path = self.config_path or spec["default"]
        try:
            service = spec["service"](config_path=config_path)
            data = service.inspect()
            validator = spec["validator"](file_path=config_path)
            return self._sort_issues(validator.run_rules(data))
        except FileNotFoundError as exc:
            if skip_missing and not self.config_path:
                self.ui.status("skip", f"{service_name}: {exc}")
                return []
            print(self.ui.c(f"[ERR] Inspection failed: {exc}", self.ui.RED), file=sys.stderr)
            return None
        except Exception as exc:
            print(self.ui.c(f"[ERR] Inspection failed: {exc}", self.ui.RED), file=sys.stderr)
            return None

    def _print_issues(self, service_name: str, issues: list[dict]) -> None:
        self.ui.section(f"Found {len(issues)} issue(s)")
        for idx, item in enumerate(issues, start=1):
            self.ui.issue(idx, service_name, item)

    @staticmethod
    def _sort_issues(issues: list[dict]) -> list[dict]:
        rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
        return sorted(issues, key=lambda item: (rank.get(item.get("severity", "info"), 4), item.get("line_number") or 0, item.get("code", "")))

    def _handle_issues(self, service_name: str, issues: list[dict]) -> bool:
        repairable = [item for item in issues if item.get("fixes")]
        for item in issues:
            if not item.get("fixes"):
                self.ui.status("info", f"No safe automatic repair is available for {item['code']}.")
        if not repairable:
            return False

        if self.yes or self.dry_run:
            selected = repairable
        else:
            selected = self._select_repairs(repairable)
            if not selected:
                self.ui.status("info", "No repairs selected.")
                return False

        fixed = self._prompt_and_repair(service_name, selected, ask=False)
        return fixed and len(selected) == len(issues)

    def _select_repairs(self, issues: list[dict]) -> list[dict]:
        selected: list[dict] = []
        for item in issues:
            self.ui.section("Repair Decision")
            self.ui.issue(None, "", item)
            self.ui.kv("Proposed repair", "")
            try:
                for message in self.repair_manager.preview_fixes(item["file_path"], item["fixes"]):
                    self.ui.bullet(message)
            except Exception as exc:
                self.ui.status("error", f"Cannot preview repair: {exc}")
                continue
            choice = self.ui.prompt("Repair this issue? [y/N]: ").strip().lower()
            if choice in {"y", "yes"}:
                selected.append(item)
            else:
                self.ui.status("info", f"Skipped {item['code']}.")
        return selected

    def _prompt_and_repair(self, service_name: str, issues: list[dict], ask: bool = True) -> bool:
        files_to_repair: dict[str, list[dict]] = {}
        for issue in issues:
            files_to_repair.setdefault(issue["file_path"], []).extend(issue["fixes"])

        for file_path, fixes in files_to_repair.items():
            self.ui.section("Planned Changes")
            self.ui.kv("File", file_path)
            try:
                for message in self.repair_manager.preview_fixes(file_path, fixes):
                    self.ui.bullet(message)
            except Exception as exc:
                self.ui.status("error", f"Cannot preview repairs: {exc}")
                return False

        if self.dry_run:
            self.ui.status("warn", "Repair preview complete. No files changed.")
            return True

        if ask:
            choice = self.ui.prompt("\nApply repairs? [Y/n]: ").strip().lower()
            if choice not in {"", "y", "yes"}:
                self.ui.status("info", "Repairs aborted by user.")
                return False

        backups: dict[str, str] = {}
        for file_path, fixes in files_to_repair.items():
            try:
                backup_path = self.backup_manager.create_backup(file_path)
                backups[file_path] = backup_path
                self.ui.status("ok", f"Backup created: {backup_path}")
                self.repair_manager.apply_fixes(file_path, fixes)
                self.ui.status("ok", f"Repairs applied: {file_path}")
            except (BackupError, RepairError, OSError) as exc:
                self.ui.status("error", f"Repair failed for {file_path}: {exc}")
                return False

        if self._verify(service_name, list(files_to_repair)):
            return True

        self.ui.status("warn", "Verification failed. Restoring backups.")
        for file_path, backup_path in backups.items():
            try:
                self.backup_manager.restore_backup(backup_path, file_path)
                self.ui.status("ok", f"Restored: {file_path}")
            except BackupError as exc:
                self.ui.status("error", f"Restore failed for {file_path}: {exc}")
        return False

    def _repair_grouped(self, items: list[tuple[str, dict]]) -> bool:
        groups: dict[str, list[dict]] = defaultdict(list)
        for service_name, item in items:
            groups[service_name].append(item)
        results = [self._handle_issues(service_name, issues) for service_name, issues in groups.items()]
        return all(results)

    def _preview_grouped(self, items: list[tuple[str, dict]]) -> bool:
        groups: dict[str, list[dict]] = defaultdict(list)
        for service_name, item in items:
            groups[service_name].append(item)
        for service_name, issues in groups.items():
            self._handle_issues(service_name, issues)
        return False

    @staticmethod
    def _loc(item: dict) -> str:
        line = f":{item['line_number']}" if item.get("line_number") else ""
        return f" ({item['file_path']}{line})"

    def _verify(self, service_name: str, paths: list[str]) -> bool:
        return self.supported_services[service_name]["verify"](paths)

    @staticmethod
    def _verify_true(paths: list[str]) -> bool:
        return True

    def _verify_ssh(self, paths: list[str]) -> bool:
        sshd = shutil.which("sshd")
        if not sshd:
            self.ui.status("warn", "sshd not found. Skipped external syntax verification.")
            return True
        config_path = paths[0]
        result = subprocess.run([sshd, "-t", "-f", config_path], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            self.ui.status("ok", "sshd syntax verification passed.")
            return True
        self.ui.status("error", f"sshd syntax verification failed: {result.stderr.strip()}")
        return False

    def _verify_nginx(self, paths: list[str]) -> bool:
        nginx = shutil.which("nginx")
        if not nginx:
            self.ui.status("warn", "nginx not found. Skipped external syntax verification.")
            return True
        result = subprocess.run([nginx, "-t", "-c", paths[0]], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            self.ui.status("ok", "nginx syntax verification passed.")
            return True
        msg = (result.stderr or result.stdout).strip()
        self.ui.status("error", f"nginx syntax verification failed: {msg}")
        return False

    def _verify_systemd(self, paths: list[str]) -> bool:
        tool = shutil.which("systemd-analyze")
        if not tool:
            self.ui.status("warn", "systemd-analyze not found. Skipped external unit verification.")
            return True
        files = [path for path in paths if Path(path).is_file()]
        if not files:
            return True
        result = subprocess.run([tool, "verify", *files], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            self.ui.status("ok", "systemd unit verification passed.")
            return True
        msg = (result.stderr or result.stdout).strip()
        self.ui.status("error", f"systemd unit verification failed: {msg}")
        return False

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

COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"


class LixetEngine:
    """Run the deterministic Inspection -> Validation -> Backup -> Repair workflow."""

    def __init__(self, dry_run: bool = False, yes: bool = False, config_path: str | None = None) -> None:
        self.dry_run = dry_run
        self.yes = yes
        self.config_path = config_path
        self.backup_manager = BackupManager()
        self.repair_manager = RepairManager()
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
            print(f"{COLOR_YELLOW}{COLOR_BOLD}[DRY RUN]{COLOR_RESET} No files will be modified.")

    def scan_service(self, service_name: str) -> bool:
        service_name = service_name.lower()
        print(f"Analyzing {COLOR_BOLD}{service_name}{COLOR_RESET}...")
        if service_name not in self.supported_services:
            print(f"{COLOR_RED}[x] Service '{service_name}' is not supported yet.{COLOR_RESET}")
            return False

        issues = self._collect_issues(service_name)
        if issues is None:
            return False

        if not issues:
            print(f"{COLOR_GREEN}[ok] No issues detected in {service_name}.{COLOR_RESET}")
            return True

        self._print_issues(service_name, issues)
        return self._handle_issues(service_name, issues)

    def run_doctor(self) -> bool:
        print(f"{COLOR_BOLD}Initiating System Doctor Scan...{COLOR_RESET}\n")
        items: list[tuple[str, dict]] = []
        for service_name in self.supported_services:
            issues = self._collect_issues(service_name, skip_missing=True)
            if issues:
                items.extend((service_name, item) for item in issues)

        print(f"\n{COLOR_BOLD}Doctor Scan Complete.{COLOR_RESET}")
        if not items:
            print(f"{COLOR_GREEN}[ok] No issues detected in supported services.{COLOR_RESET}")
            return True

        for idx, (service_name, item) in enumerate(items, start=1):
            loc = self._loc(item)
            print(f"  [{idx}] {service_name}: {item['severity']} {item['code']} - {item['description']}{loc}")

        if self.yes:
            return self._repair_grouped(items)

        if self.dry_run:
            return self._preview_grouped(items)

        choice = input("\nChoose a problem number to repair, 'a' for all repairable, or Enter to abort: ").strip().lower()
        if not choice:
            print(f"{COLOR_CYAN}Doctor repair aborted by user.{COLOR_RESET}")
            return False
        if choice == "a":
            return self._repair_grouped(items)
        try:
            selected = items[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"{COLOR_RED}[x] Invalid selection.{COLOR_RESET}")
            return False
        return self._handle_issues(selected[0], [selected[1]])

    def _collect_issues(self, service_name: str, skip_missing: bool = False) -> list[dict] | None:
        spec = self.supported_services[service_name]
        config_path = self.config_path or spec["default"]
        try:
            service = spec["service"](config_path=config_path)
            data = service.inspect()
            validator = spec["validator"](file_path=config_path)
            return validator.run_rules(data)
        except FileNotFoundError as exc:
            if skip_missing and not self.config_path:
                print(f"{COLOR_CYAN}[skip] {service_name}: {exc}{COLOR_RESET}")
                return []
            print(f"{COLOR_RED}[x] Inspection failed: {exc}{COLOR_RESET}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"{COLOR_RED}[x] Inspection failed: {exc}{COLOR_RESET}", file=sys.stderr)
            return None

    def _print_issues(self, service_name: str, issues: list[dict]) -> None:
        print(f"{COLOR_YELLOW}[!] Found {len(issues)} issue(s) in {service_name}:{COLOR_RESET}")
        for idx, item in enumerate(issues, start=1):
            loc = self._loc(item)
            print(f"  [{idx}] {item['severity']} {item['code']} - {item['description']}{loc}")

    def _handle_issues(self, service_name: str, issues: list[dict]) -> bool:
        repairable = [item for item in issues if item.get("fixes")]
        for item in issues:
            if not item.get("fixes"):
                print(f"  - no automatic repair for {item['code']}")
        if not repairable:
            return False

        if self.yes or self.dry_run:
            selected = repairable
        else:
            selected = self._select_repairs(repairable)
            if not selected:
                print(f"{COLOR_CYAN}No repairs selected.{COLOR_RESET}")
                return False

        fixed = self._prompt_and_repair(service_name, selected, ask=False)
        return fixed and len(selected) == len(issues)

    def _select_repairs(self, issues: list[dict]) -> list[dict]:
        selected: list[dict] = []
        for item in issues:
            print(f"\nIssue: {item['severity']} {item['code']}")
            print(f"Description: {item['description']}")
            print(f"Location: {item['file_path']}{':' + str(item['line_number']) if item.get('line_number') else ''}")
            print("Proposed repair:")
            try:
                for message in self.repair_manager.preview_fixes(item["file_path"], item["fixes"]):
                    print(f"  - {message}")
            except Exception as exc:
                print(f"{COLOR_RED}[x] Cannot preview repair: {exc}{COLOR_RESET}")
                continue
            choice = input("Repair this issue? [y/N]: ").strip().lower()
            if choice in {"y", "yes"}:
                selected.append(item)
            else:
                print(f"{COLOR_CYAN}Skipped {item['code']}.{COLOR_RESET}")
        return selected

    def _prompt_and_repair(self, service_name: str, issues: list[dict], ask: bool = True) -> bool:
        files_to_repair: dict[str, list[dict]] = {}
        for issue in issues:
            files_to_repair.setdefault(issue["file_path"], []).extend(issue["fixes"])

        for file_path, fixes in files_to_repair.items():
            print(f"\nPlanned changes for {file_path}:")
            try:
                for message in self.repair_manager.preview_fixes(file_path, fixes):
                    print(f"  - {message}")
            except Exception as exc:
                print(f"{COLOR_RED}[x] Cannot preview repairs: {exc}{COLOR_RESET}")
                return False

        if self.dry_run:
            print(f"\n{COLOR_YELLOW}[DRY RUN]{COLOR_RESET} Repair preview complete; no files changed.")
            return True

        if ask:
            choice = input("\nApply repairs? [Y/n]: ").strip().lower()
            if choice not in {"", "y", "yes"}:
                print(f"{COLOR_CYAN}Repairs aborted by user.{COLOR_RESET}")
                return False

        backups: dict[str, str] = {}
        for file_path, fixes in files_to_repair.items():
            try:
                backup_path = self.backup_manager.create_backup(file_path)
                backups[file_path] = backup_path
                print(f"{COLOR_GREEN}[ok] Backup created:{COLOR_RESET} {backup_path}")
                self.repair_manager.apply_fixes(file_path, fixes)
                print(f"{COLOR_GREEN}[ok] Repairs applied:{COLOR_RESET} {file_path}")
            except (BackupError, RepairError, OSError) as exc:
                print(f"{COLOR_RED}[x] Repair failed for {file_path}: {exc}{COLOR_RESET}")
                return False

        if self._verify(service_name, list(files_to_repair)):
            return True

        print(f"{COLOR_YELLOW}[!] Verification failed; restoring backups.{COLOR_RESET}")
        for file_path, backup_path in backups.items():
            try:
                self.backup_manager.restore_backup(backup_path, file_path)
                print(f"{COLOR_GREEN}[ok] Restored:{COLOR_RESET} {file_path}")
            except BackupError as exc:
                print(f"{COLOR_RED}[x] Restore failed for {file_path}: {exc}{COLOR_RESET}")
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
            print(f"{COLOR_YELLOW}[!] sshd not found; skipped external syntax verification.{COLOR_RESET}")
            return True
        config_path = paths[0]
        result = subprocess.run([sshd, "-t", "-f", config_path], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            print(f"{COLOR_GREEN}[ok] sshd syntax verification passed.{COLOR_RESET}")
            return True
        print(f"{COLOR_RED}[x] sshd syntax verification failed:{COLOR_RESET} {result.stderr.strip()}")
        return False

    def _verify_nginx(self, paths: list[str]) -> bool:
        nginx = shutil.which("nginx")
        if not nginx:
            print(f"{COLOR_YELLOW}[!] nginx not found; skipped external syntax verification.{COLOR_RESET}")
            return True
        result = subprocess.run([nginx, "-t", "-c", paths[0]], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            print(f"{COLOR_GREEN}[ok] nginx syntax verification passed.{COLOR_RESET}")
            return True
        msg = (result.stderr or result.stdout).strip()
        print(f"{COLOR_RED}[x] nginx syntax verification failed:{COLOR_RESET} {msg}")
        return False

    def _verify_systemd(self, paths: list[str]) -> bool:
        tool = shutil.which("systemd-analyze")
        if not tool:
            print(f"{COLOR_YELLOW}[!] systemd-analyze not found; skipped external unit verification.{COLOR_RESET}")
            return True
        files = [path for path in paths if Path(path).is_file()]
        if not files:
            return True
        result = subprocess.run([tool, "verify", *files], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            print(f"{COLOR_GREEN}[ok] systemd unit verification passed.{COLOR_RESET}")
            return True
        msg = (result.stderr or result.stdout).strip()
        print(f"{COLOR_RED}[x] systemd unit verification failed:{COLOR_RESET} {msg}")
        return False

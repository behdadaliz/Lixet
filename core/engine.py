# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Core orchestration for Lixet scans and repairs."""

from __future__ import annotations

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
from validators.helpers import run_command
from validators.helpers import issue as make_issue
from utils.ui import UI


class LixetEngine:
    """Run the deterministic Inspection -> Validation -> Backup -> Repair workflow."""

    def __init__(
        self,
        dry_run: bool = False,
        yes: bool = False,
        config_path: str | None = None,
        no_color: bool = False,
    ) -> None:
        self.dry_run = dry_run
        self.yes = yes
        self.config_path = config_path
        self.backup_manager = BackupManager()
        self.repair_manager = RepairManager()
        self.ui = UI(no_color=no_color)
        self.aliases = {
            "sshd": "ssh",
            "openssh": "ssh",
            "network": "networking",
        }
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
        service_name = self._service_name(service_name)
        self.ui.banner(f"Scanning {service_name}", "Deterministic configuration inspection")
        if service_name not in self.supported_services:
            self.ui.status("error", f"Service '{service_name}' is not supported.")
            self.ui.kv("Supported", ", ".join(self.supported_services))
            return False

        issues = self._collect_issues(service_name)
        if issues is None:
            return False

        if not issues:
            self.ui.status("ok", f"No issues detected in {service_name}.")
            self._scan_summary(service_name, [])
            return True

        self._print_issues(service_name, issues)
        self._scan_summary(service_name, issues)
        return self._select_from_scan(service_name, issues)

    def run_doctor(self) -> bool:
        self.ui.banner("Lixet Doctor", "Scanning supported services")
        items: list[tuple[str, dict]] = []
        scanned: list[str] = []
        skipped: list[str] = []
        for service_name in self.supported_services:
            issues = self._collect_issues(service_name, skip_missing=True)
            if issues is None:
                skipped.append(service_name)
                continue
            scanned.append(service_name)
            if issues:
                items.extend((service_name, item) for item in issues)
        items = self._sort_items(items)

        self._doctor_summary(items, scanned, skipped)
        if not items:
            self.ui.status("ok", "No issues detected in supported services.")
            return True

        for idx, (service_name, item) in enumerate(items, start=1):
            self.ui.issue(idx, service_name, item)

        if not any(item.get("fixes") for _, item in items):
            self.ui.status("info", "No safe automatic repairs are available.")
            return False

        if self.yes:
            return self._repair_grouped(items, ask=False)

        if self.dry_run:
            return self._preview_grouped(items)

        choice = self.ui.prompt("\nChoose a problem number, 'a' for all repairable, or Enter to abort: ").strip().lower()
        if not choice:
            self.ui.status("info", "Doctor repair aborted by user.")
            return False
        if choice == "a":
            return self._repair_grouped(items, ask=True)
        try:
            selected = items[int(choice) - 1]
        except (ValueError, IndexError):
            self.ui.status("error", "Invalid selection.")
            return False
        return self._repair_issue_set(selected[0], [selected[1]], ask=True)

    def _select_from_scan(self, service_name: str, issues: list[dict]) -> bool:
        if not any(item.get("fixes") for item in issues):
            self.ui.status("info", "No safe automatic repairs are available.")
            return False

        if self.yes:
            return self._repair_issue_set(service_name, issues, ask=False)
        if self.dry_run:
            return self._repair_issue_set(service_name, issues, ask=False)

        choice = self.ui.prompt("\nChoose a problem number, 'a' for all repairable, or Enter to abort: ").strip().lower()
        if not choice:
            self.ui.status("info", "Scan repair aborted by user.")
            return False
        if choice == "a":
            return self._repair_issue_set(service_name, issues, ask=True)
        try:
            selected = issues[int(choice) - 1]
        except (ValueError, IndexError):
            self.ui.status("error", "Invalid selection.")
            return False
        return self._repair_issue_set(service_name, [selected], ask=True)

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
                return None
            return [self._inspection_issue(service_name, config_path, str(exc), "CONFIG_NOT_FOUND")]
        except PermissionError as exc:
            return [self._inspection_issue(service_name, config_path, str(exc), "CONFIG_UNREADABLE")]
        except Exception as exc:
            print(self.ui.c(f"[ERR] Inspection failed: {exc}", self.ui.RED), file=sys.stderr)
            return None

    def _print_issues(self, service_name: str, issues: list[dict]) -> None:
        self.ui.section(f"Found {len(issues)} issue(s)")
        for idx, item in enumerate(issues, start=1):
            self.ui.issue(idx, service_name, item)

    @staticmethod
    def _sort_issues(issues: list[dict]) -> list[dict]:
        return sorted(issues, key=lambda item: LixetEngine._issue_key(item))

    @staticmethod
    def _sort_items(items: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        return sorted(items, key=lambda pair: (LixetEngine._issue_key(pair[1]), pair[0]))

    @staticmethod
    def _issue_key(item: dict) -> tuple[int, int, str]:
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        return (rank.get(str(item.get("severity", "info")).lower(), 5), item.get("line_number") or 0, item.get("code", ""))

    def _scan_summary(self, service_name: str, issues: list[dict]) -> None:
        self.ui.section("Scan Summary")
        self.ui.kv("Service", service_name)
        self.ui.kv("Status", "healthy" if not issues else "issues found")
        self.ui.kv("Issues", self._count_text(issues))
        if issues:
            self.ui.kv("Repairable", str(sum(1 for item in issues if item.get("fixes"))))

    def _doctor_summary(self, items: list[tuple[str, dict]], scanned: list[str], skipped: list[str]) -> None:
        self.ui.section("Doctor Summary")
        healthy = [name for name in scanned if not any(svc == name for svc, _ in items)]
        self.ui.kv("Services scanned", ", ".join(scanned) if scanned else "none")
        if skipped:
            self.ui.kv("Services skipped", ", ".join(skipped))
        self.ui.kv("Healthy services", ", ".join(healthy) if healthy else "none")
        self.ui.kv("Issues found", self._count_text([item for _, item in items]))
        self.ui.kv("Repairable", str(sum(1 for _, item in items if item.get("fixes"))))

    @staticmethod
    def _count_text(issues: list[dict]) -> str:
        if not issues:
            return "none"
        order = ["critical", "high", "medium", "low", "info"]
        parts = []
        for sev in order:
            count = sum(1 for item in issues if str(item.get("severity", "")).lower() == sev)
            if count:
                parts.append(f"{count} {sev}")
        return ", ".join(parts) if parts else str(len(issues))

    def _service_name(self, name: str) -> str:
        key = name.lower()
        return self.aliases.get(key, key)

    @staticmethod
    def _inspection_issue(service_name: str, config_path: str, evidence: str, suffix: str) -> dict:
        return make_issue(
            f"{service_name.upper()}_{suffix}",
            "high",
            "Configuration inspection failed.",
            config_path,
            [],
            None,
            service_name,
            evidence,
            "No safe automatic repair available.",
        )

    def _repair_issue_set(self, service_name: str, issues: list[dict], ask: bool) -> bool:
        repairable = [item for item in issues if item.get("fixes")]
        for item in issues:
            if not item.get("fixes"):
                self.ui.status("info", f"No safe automatic repair is available for {item['code']}.")
        if not repairable:
            return False

        fixed = self._prompt_and_repair(service_name, repairable, ask=ask and not self.yes)
        return fixed and len(repairable) == len(issues)

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
            return False

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

    def _repair_grouped(self, items: list[tuple[str, dict]], ask: bool) -> bool:
        groups: dict[str, list[dict]] = defaultdict(list)
        for service_name, item in items:
            groups[service_name].append(item)
        results = [self._repair_issue_set(service_name, issues, ask=ask) for service_name, issues in groups.items()]
        return all(results)

    def _preview_grouped(self, items: list[tuple[str, dict]]) -> bool:
        groups: dict[str, list[dict]] = defaultdict(list)
        for service_name, item in items:
            groups[service_name].append(item)
        for service_name, issues in groups.items():
            self._repair_issue_set(service_name, issues, ask=False)
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
        config_path = paths[0]
        result = run_command(["sshd", "-t", "-f", config_path])
        if not result:
            self.ui.status("warn", "sshd not found. Skipped external syntax verification.")
            return True
        if result["returncode"] == 0:
            self.ui.status("ok", "sshd syntax verification passed.")
            return True
        self.ui.status("error", f"sshd syntax verification failed: {result['evidence']}")
        return False

    def _verify_nginx(self, paths: list[str]) -> bool:
        result = run_command(["nginx", "-t", "-c", paths[0]])
        if not result:
            self.ui.status("warn", "nginx not found. Skipped external syntax verification.")
            return True
        if result["returncode"] == 0:
            self.ui.status("ok", "nginx syntax verification passed.")
            return True
        self.ui.status("error", f"nginx syntax verification failed: {result['evidence']}")
        return False

    def _verify_systemd(self, paths: list[str]) -> bool:
        files = [path for path in paths if Path(path).is_file()]
        if not files:
            return True
        result = run_command(["systemd-analyze", "verify", *files])
        if not result:
            self.ui.status("warn", "systemd-analyze not found. Skipped external unit verification.")
            return True
        if result["returncode"] == 0:
            self.ui.status("ok", "systemd unit verification passed.")
            return True
        self.ui.status("error", f"systemd unit verification failed: {result['evidence']}")
        return False

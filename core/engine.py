# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Service discovery, diagnosis, authorization, repair, and verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backup.manager import BackupManager, RollbackError
from core.models import ExitCode, VerificationResult, VerificationState
from repair.manager import RepairError, RepairManager
from repair.snapshot import FileSnapshot, SnapshotError
from repair.transaction import RepairPlan, RepairTransaction, TransactionError
from services.dns_service import DNSService
from services.fstab_service import FstabService
from services.networking_service import NetworkingService
from services.nginx_service import NginxService
from services.ssh_service import SSHService
from services.sudoers_service import SudoersService
from services.sysctl_service import SysctlService
from services.systemd_service import SystemdService
from services.ufw_service import UFWService
from utils.command import CommandExecutor, CommandRunner
from utils.ui import UI
from validators.dns_validator import DNSValidator
from validators.fstab_validator import FstabValidator
from validators.helpers import issue as make_issue
from validators.networking_validator import NetworkingValidator
from validators.nginx_validator import NginxValidator
from validators.ssh_validator import SSHValidator
from validators.sudoers_validator import SudoersValidator
from validators.sysctl_validator import SysctlValidator
from validators.systemd_validator import SystemdValidator
from validators.ufw_validator import UFWValidator


@dataclass
class InspectionResult:
    service: str
    status: str
    path: str
    issues: list[dict]
    data: dict | None
    snapshots: dict[str, FileSnapshot]
    message: str = ""


class LixetEngine:
    """Coordinate the deterministic inspection-to-verification workflow."""

    SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    EXTERNAL_REQUIRED = {"ssh", "nginx", "sudoers", "fstab", "systemd"}

    def __init__(
        self,
        dry_run: bool = False,
        yes: bool = False,
        config_path: str | None = None,
        no_color: bool = False,
        backup_dir: str | Path | None = None,
        lock_dir: str | Path = "/run/lock/lixet",
        filesystem_root: str | Path | None = None,
        runner: CommandExecutor | None = None,
        ui: UI | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.yes = yes
        self.config_path = config_path
        self.filesystem_root = Path(filesystem_root) if filesystem_root is not None else None
        self.runner = runner or CommandRunner()
        self.ui = ui or UI(no_color=no_color)
        self.backup_manager = BackupManager(backup_dir)
        self.repair_manager = RepairManager()
        self.transaction = RepairTransaction(self.backup_manager, self.repair_manager, lock_dir)
        self._last: dict[str, InspectionResult] = {}
        self.aliases = {
            "sshd": "ssh",
            "openssh": "ssh",
            "network": "networking",
            "hosts": "networking",
            "firewall": "ufw",
        }
        self.supported_services = {
            "ssh": self._spec(
                SSHService,
                SSHValidator,
                "/etc/ssh/sshd_config",
                "sshd",
                False,
                False,
                "OpenSSH server configuration and includes",
            ),
            "nginx": self._spec(
                NginxService,
                NginxValidator,
                "/etc/nginx/nginx.conf",
                "nginx",
                False,
                False,
                "Nginx root configuration and includes",
            ),
            "ufw": self._spec(
                UFWService,
                UFWValidator,
                "/etc/ufw/ufw.conf",
                "ufw",
                False,
                False,
                "UFW state, defaults, and runtime status",
            ),
            "dns": self._spec(
                DNSService,
                DNSValidator,
                "/etc/resolv.conf",
                "resolvectl",
                True,
                True,
                "Resolver syntax and local manager state",
            ),
            "networking": self._spec(
                NetworkingService,
                NetworkingValidator,
                "/etc/hosts",
                "ip",
                True,
                True,
                "Hosts file and local network state",
            ),
            "systemd": self._spec(
                SystemdService,
                SystemdValidator,
                "/etc/systemd/system",
                "systemctl",
                False,
                False,
                "systemd runtime, units, and drop-ins",
            ),
            "sudoers": self._spec(
                SudoersService,
                SudoersValidator,
                "/etc/sudoers",
                "visudo",
                False,
                False,
                "sudoers syntax through visudo",
            ),
            "fstab": self._spec(
                FstabService, FstabValidator, "/etc/fstab", "findmnt", False, True, "fstab syntax through findmnt"
            ),
            "sysctl": self._spec(
                SysctlService,
                SysctlValidator,
                "/etc/sysctl.conf",
                "sysctl",
                False,
                True,
                "sysctl load order and effective overrides",
            ),
        }
        if self.dry_run:
            self.ui.status("warn", "Dry run enabled. No files or backups will be created.")

    @staticmethod
    def _spec(
        service, validator, default: str, command: str, required: bool, config_only: bool, description: str
    ) -> dict:
        return {
            "service": service,
            "validator": validator,
            "default": default,
            "command": command,
            "required": required,
            "config_only": config_only,
            "description": description,
        }

    def show_services(self) -> ExitCode:
        self.ui.banner("Supported Services", "Services Lixet can inspect")
        width = max([len(name) for name in self.supported_services] + [len(alias) for alias in self.aliases])
        for name, spec in self.supported_services.items():
            label = self.ui.c(name.ljust(width), self.ui.BOLD + self.ui.CYAN)
            print(f"  {label}  {spec['description']}")
        self.ui.section("Aliases")
        for alias, service_name in sorted(self.aliases.items()):
            print(f"  {self.ui.c(alias.ljust(width), self.ui.BOLD)}  -> {self.ui.c(service_name, self.ui.CYAN)}")
        return ExitCode.OK

    def scan_service(self, service_name: str) -> ExitCode:
        service_name = self._service_name(service_name)
        self.ui.banner(f"Scanning {service_name}", "Deterministic configuration inspection")
        if service_name not in self.supported_services:
            self.ui.status("error", f"Service '{service_name}' is not supported.")
            self.ui.kv("Supported", ", ".join(sorted(self.supported_services)))
            return ExitCode.USAGE

        result = self._inspect(service_name, custom_path=self.config_path, doctor=False)
        self._show_inspection(result)
        if result.status == "failed":
            return ExitCode.INSPECTION_FAILED
        if not result.issues:
            self.ui.status("ok", f"No issues detected in {service_name}.")
            return ExitCode.OK
        return self._offer_repairs([(service_name, item) for item in result.issues], doctor=False)

    def run_doctor(self) -> ExitCode:
        self.ui.banner("Lixet Doctor", "Scanning supported services")
        results = [self._inspect(name, doctor=True) for name in self.supported_services]
        items = self._sort_items([(result.service, item) for result in results for item in result.issues])
        self._doctor_summary(results, items)
        for index, (service, item) in enumerate(items, start=1):
            self.ui.issue(index, service, item)

        if any(result.status == "failed" for result in results):
            return ExitCode.INSPECTION_FAILED
        if not items:
            incomplete = [result for result in results if result.status != "checked"]
            if incomplete:
                self.ui.status("warn", "Doctor completed with checks that were not run.")
                return ExitCode.ISSUES
            self.ui.status("ok", "No issues detected in completed checks.")
            return ExitCode.OK
        return self._offer_repairs(items, doctor=True)

    def _inspect(self, service_name: str, custom_path: str | None = None, doctor: bool = False) -> InspectionResult:
        spec = self.supported_services[service_name]
        path = custom_path or self._system_path(spec["default"])
        try:
            service = spec["service"](config_path=path, runner=self.runner)
            data = service.inspect()
            validator = spec["validator"](file_path=path)
            issues = self._sort_issues(validator.run_rules(data))
            snapshots = self._snapshots(data)
            self._attach_snapshot_details(issues, snapshots)
            status = "checked"
            message = ""
            if data.get("missing_config"):
                installed = self.runner.resolve(str(spec["command"])) is not None
                status = (
                    "configuration missing"
                    if spec["required"]
                    else ("configuration absent" if spec["config_only"] or installed else "not installed")
                )
                message = f"Expected configuration is absent: {path}"
            elif data.get("config_absent"):
                installed = self.runner.resolve(str(spec["command"])) is not None
                status = "checked" if installed else "unsupported environment"
                message = "No local unit directory was found; runtime checks were still attempted."
            result = InspectionResult(service_name, status, path, issues, data, snapshots, message)
        except FileNotFoundError as exc:
            installed = self.runner.resolve(str(spec["command"])) is not None
            if doctor and not spec["required"] and not installed and not spec["config_only"]:
                result = InspectionResult(service_name, "not installed", path, [], None, {}, str(exc))
            else:
                item = self._inspection_issue(service_name, path, str(exc), "CONFIG_NOT_FOUND", "high")
                result = InspectionResult(service_name, "configuration missing", path, [item], None, {}, str(exc))
        except PermissionError as exc:
            item = self._inspection_issue(service_name, path, str(exc), "CONFIG_PERMISSION_DENIED", "high")
            result = InspectionResult(service_name, "failed", path, [item], None, {}, str(exc))
        except (OSError, ValueError, SnapshotError) as exc:
            item = self._inspection_issue(service_name, path, str(exc), "INSPECTION_FAILED", "high")
            result = InspectionResult(service_name, "failed", path, [item], None, {}, str(exc))
        except Exception as exc:
            item = self._inspection_issue(service_name, path, str(exc), "INSPECTION_FAILED", "critical")
            result = InspectionResult(service_name, "failed", path, [item], None, {}, str(exc))
        self._last[service_name] = result
        return result

    def _offer_repairs(self, items: list[tuple[str, dict]], doctor: bool) -> ExitCode:
        repairable = [(service, item) for service, item in items if self._is_repairable(item)]
        if not repairable:
            self.ui.status("info", "No automatic repairs are available for the detected issues.")
            return ExitCode.ISSUES
        if self.dry_run:
            return self._preview(repairable)
        if self.yes:
            safe = [(service, item) for service, item in repairable if item.get("repair_level") == "safe"]
            for _service, item in repairable:
                if item.get("repair_level") == "guarded":
                    self.ui.status(
                        "info", f"Skipped guarded repair: explicit interactive approval is required. ({item['code']})"
                    )
            if not safe:
                return ExitCode.ISSUES
            return self._execute_repairs(safe)
        if not self.ui.can_prompt():
            self.ui.status(
                "info", "Repairs require an interactive terminal. Use --dry-run or -y for proven safe repairs."
            )
            return ExitCode.ISSUES

        prompt = "\nChoose a problem number, 'a' for all repairable, or Enter to abort: "
        choice = self.ui.prompt(prompt).strip().lower()
        if not choice:
            self.ui.status("info", "Repair aborted by user.")
            return ExitCode.ISSUES
        if choice == "a":
            selected = repairable
        else:
            try:
                selected_item = items[int(choice) - 1]
            except (ValueError, IndexError):
                self.ui.status("error", "Invalid selection.")
                return ExitCode.USAGE
            if not self._is_repairable(selected_item[1]):
                self.ui.status("info", "The selected issue has no automatic repair.")
                return ExitCode.ISSUES
            selected = [selected_item]
        approved = self._authorize(selected)
        if not approved:
            return ExitCode.ISSUES
        return self._execute_repairs(approved)

    def _authorize(self, items: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        approved: list[tuple[str, dict]] = []
        safe = [(service, item) for service, item in items if item.get("repair_level") == "safe"]
        guarded = [(service, item) for service, item in items if item.get("repair_level") == "guarded"]
        if safe:
            choice = self.ui.prompt(f"Apply {len(safe)} safe repair(s)? [y/N]: ").strip().lower()
            if choice in {"y", "yes"}:
                approved.extend(safe)
        for service, item in guarded:
            self.ui.status("warn", f"Guarded repair: {service} / {item['code']}")
            if item.get("risk_note"):
                self.ui.kv("Risk", str(item["risk_note"]))
            choice = self.ui.prompt("Type APPLY to authorize this guarded repair: ").strip()
            if choice == "APPLY":
                approved.append((service, item))
            else:
                self.ui.status("info", f"Guarded repair skipped: {item['code']}")
        return approved

    def _preview(self, items: list[tuple[str, dict]]) -> ExitCode:
        try:
            for plan in self._plans(items):
                self.ui.section("Planned Changes")
                self.ui.kv("File", plan.path)
                if plan.snapshot.is_symlink:
                    self.ui.kv("Resolved", plan.snapshot.resolved_path)
                for message in self.repair_manager.preview_fixes(plan.path, plan.fixes, plan.snapshot):
                    self.ui.bullet(message)
        except (RepairError, SnapshotError, TransactionError) as exc:
            self.ui.status("error", f"Cannot preview repairs: {exc}")
            return ExitCode.REPAIR_FAILED
        self.ui.status("warn", "Dry-run complete. No files or backups were created.")
        return ExitCode.ISSUES

    def _execute_repairs(self, items: list[tuple[str, dict]]) -> ExitCode:
        if not items:
            return ExitCode.ISSUES
        try:
            plans = self._plans(items)
            for plan in plans:
                self.ui.section("Planned Changes")
                self.ui.kv("File", plan.path)
                if plan.snapshot.is_symlink:
                    self.ui.kv("Resolved", plan.snapshot.resolved_path)
                for message in self.repair_manager.preview_fixes(plan.path, plan.fixes, plan.snapshot):
                    self.ui.bullet(message)
            result = self.transaction.execute(plans, lambda: self._verify_items(items))
        except RollbackError as exc:
            self.ui.status("critical", str(exc))
            return ExitCode.ROLLBACK_FAILED
        except (RepairError, SnapshotError, TransactionError) as exc:
            self.ui.status("error", f"Repair transaction failed: {exc}")
            return ExitCode.REPAIR_FAILED
        self.ui.status("ok", f"Repair transaction completed: {result.verification.state.value}.")
        for backup in result.backups:
            self.ui.kv("Backup", backup)
        return self._rescan_after_repair({service for service, _item in items})

    def _plans(self, items: list[tuple[str, dict]]) -> list[RepairPlan]:
        grouped: dict[str, dict] = {}
        for service, item in items:
            path = str(item["file_path"])
            result = self._last.get(service)
            snapshot = result.snapshots.get(str(Path(path).absolute())) if result else None
            if snapshot is None:
                raise TransactionError(f"No inspection snapshot is available for {path}")
            group = grouped.setdefault(path, {"snapshot": snapshot, "service": service, "fixes": [], "ids": []})
            if group["service"] != service:
                raise TransactionError(f"Multiple services attempted to repair the same file: {path}")
            group["fixes"].extend(item.get("fixes") or [])
            group["ids"].append(str(item["id"]))
        return [
            RepairPlan(path, group["fixes"], group["snapshot"], group["service"], group["ids"])
            for path, group in grouped.items()
        ]

    def _verify_items(self, items: list[tuple[str, dict]]) -> VerificationResult:
        grouped: dict[str, list[dict]] = {}
        for service, item in items:
            grouped.setdefault(service, []).append(item)
        external_used = False
        for service, repaired in grouped.items():
            before = self._last[service]
            after = self._inspect(service, custom_path=self.config_path if len(grouped) == 1 else None, doctor=False)
            if after.status != "checked":
                return VerificationResult(
                    VerificationState.FAILED, f"Post-repair inspection failed for {service}: {after.message}"
                )
            remaining = {(item["code"], str(Path(item["file_path"]).absolute())) for item in after.issues}
            for item in repaired:
                key = (item["code"], str(Path(item["file_path"]).absolute()))
                if key in remaining:
                    return VerificationResult(
                        VerificationState.FAILED, f"Repaired issue is still present: {item['code']}"
                    )
            threshold = min(self.SEVERITY.get(str(item.get("severity", "info")).lower(), 4) for item in repaired)
            before_keys = {self._issue_identity(item) for item in before.issues}
            new_serious = [
                item
                for item in after.issues
                if self.SEVERITY.get(str(item.get("severity", "info")).lower(), 4) <= threshold
                and self._issue_identity(item) not in before_keys
            ]
            if new_serious:
                return VerificationResult(
                    VerificationState.FAILED, f"New equal-or-higher severity issue appeared: {new_serious[0]['code']}"
                )
            external = self._external_result(service, after.data or {})
            if service in self.EXTERNAL_REQUIRED:
                if external is None:
                    return VerificationResult(
                        VerificationState.EXTERNAL_UNAVAILABLE,
                        f"Required external verifier is unavailable for {service}",
                    )
                external_used = True
                if external.get("returncode") != 0:
                    return VerificationResult(
                        VerificationState.FAILED,
                        f"External verification failed for {service}: {external.get('evidence') or 'no output'}",
                    )
        state = VerificationState.VERIFIED if external_used else VerificationState.INTERNALLY_VERIFIED
        return VerificationResult(state, "Post-repair validation passed")

    @staticmethod
    def _external_result(service: str, data: dict) -> dict | None:
        key = {"ssh": "config_test", "nginx": "config_test", "sudoers": "config_test", "fstab": "findmnt_verify"}.get(
            service
        )
        return data.get(key) if key else None

    def _rescan_after_repair(self, services: set[str]) -> ExitCode:
        unresolved = False
        failed = False
        for service in sorted(services):
            result = self._inspect(service, custom_path=self.config_path if len(services) == 1 else None, doctor=False)
            self._show_inspection(result)
            unresolved = unresolved or bool(result.issues)
            failed = failed or result.status == "failed"
        if failed:
            return ExitCode.INSPECTION_FAILED
        return ExitCode.ISSUES if unresolved else ExitCode.OK

    def _show_inspection(self, result: InspectionResult) -> None:
        self.ui.section("Scan Summary")
        self.ui.kv("Service", result.service)
        self.ui.kv("Check status", result.status)
        self.ui.kv("Target", result.path)
        self.ui.kv("Issues", self._count_text(result.issues))
        if result.message and result.status != "checked":
            self.ui.kv("Detail", result.message)
        if result.issues:
            self.ui.kv("Repairable", self._repairable_text(result.issues))
            self.ui.section(f"Found {len(result.issues)} issue(s)")
            for index, item in enumerate(result.issues, start=1):
                self.ui.issue(index, result.service, item)

    def _doctor_summary(self, results: list[InspectionResult], items: list[tuple[str, dict]]) -> None:
        self.ui.section("Doctor Summary")
        for result in results:
            detail = f" - {result.message}" if result.message else ""
            self.ui.kv(result.service, f"{result.status}{detail}")
        self.ui.kv("Issues found", self._count_text([item for _service, item in items]))
        self.ui.kv("Repairable", self._repairable_text([item for _service, item in items]))

    def _system_path(self, path: str) -> str:
        if self.filesystem_root is None:
            return path
        return str(self.filesystem_root / path.lstrip("/\\"))

    @staticmethod
    def _snapshots(data: object) -> dict[str, FileSnapshot]:
        found: dict[str, FileSnapshot] = {}

        def visit(value: object) -> None:
            if isinstance(value, dict):
                snapshot = value.get("snapshot")
                if isinstance(snapshot, FileSnapshot):
                    found[str(Path(snapshot.original_path).absolute())] = snapshot
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(data)
        return found

    @staticmethod
    def _attach_snapshot_details(issues: list[dict], snapshots: dict[str, FileSnapshot]) -> None:
        for item in issues:
            snapshot = snapshots.get(str(Path(item["file_path"]).absolute()))
            if not snapshot:
                continue
            item["resolved_path"] = snapshot.resolved_path
            if snapshot.is_symlink:
                item["symlink_target"] = snapshot.symlink_target

    @staticmethod
    def _inspection_issue(service: str, path: str, evidence: str, suffix: str, severity: str) -> dict:
        return make_issue(
            f"{service.upper()}_{suffix}",
            severity,
            "Configuration inspection did not complete.",
            path,
            [],
            None,
            service,
            evidence,
            "No automatic repair is available.",
            None,
            "unsafe",
        )

    def _service_name(self, name: str) -> str:
        key = name.lower()
        return self.aliases.get(key, key)

    @classmethod
    def _sort_issues(cls, issues: list[dict]) -> list[dict]:
        return sorted(issues, key=cls._issue_key)

    @classmethod
    def _sort_items(cls, items: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        return sorted(items, key=lambda pair: (cls._issue_key(pair[1]), pair[0]))

    @classmethod
    def _issue_key(cls, item: dict) -> tuple[int, str, int, str]:
        return (
            cls.SEVERITY.get(str(item.get("severity", "info")).lower(), 5),
            str(item.get("file_path") or ""),
            int(item.get("line_number") or 0),
            str(item.get("code") or ""),
        )

    @staticmethod
    def _issue_identity(item: dict) -> tuple[str, str, int]:
        return (
            str(item.get("code")),
            str(Path(item.get("file_path") or "").absolute()),
            int(item.get("line_number") or 0),
        )

    @staticmethod
    def _is_repairable(item: dict) -> bool:
        return bool(item.get("repairable") and item.get("fixes") and item.get("repair_level") in {"safe", "guarded"})

    @classmethod
    def _repairable_text(cls, issues: list[dict]) -> str:
        safe = sum(1 for item in issues if cls._is_repairable(item) and item.get("repair_level") == "safe")
        guarded = sum(1 for item in issues if cls._is_repairable(item) and item.get("repair_level") == "guarded")
        parts = [text for count, text in ((safe, f"{safe} safe"), (guarded, f"{guarded} guarded")) if count]
        return ", ".join(parts) if parts else "0"

    @classmethod
    def _count_text(cls, issues: list[dict]) -> str:
        if not issues:
            return "none"
        parts = []
        for severity in ("critical", "high", "medium", "low", "info"):
            count = sum(1 for item in issues if str(item.get("severity", "")).lower() == severity)
            if count:
                parts.append(f"{count} {severity}")
        return ", ".join(parts)

    @staticmethod
    def _verify_true(_paths: list[str]) -> bool:
        return False

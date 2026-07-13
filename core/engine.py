# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Service discovery, diagnosis, authorization, repair, and verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backup.manager import BackupError, BackupManager, RollbackError
from core.detector import DetectionResult, DetectionStatus, TargetDetector
from core.models import ExitCode, VerificationResult, VerificationState
from core.registry import aliases, get_service, iter_services, resolve_service_name, service_names
from repair.manager import RepairError, RepairManager
from repair.snapshot import FileSnapshot, SnapshotError, require_unchanged
from repair.transaction import RepairPlan, RepairTransaction, TransactionError
from utils.command import CommandExecutor, CommandRunner
from utils.diff import DiffFile, render_diff, repaired_bytes
from utils.selection import SelectionAction, parse_selection
from utils.ui import UI
from validators.helpers import issue as make_issue


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
    EXTERNAL_REQUIRED = {"ssh", "nginx", "sudoers", "fstab", "systemd", "fail2ban"}

    def __init__(
        self,
        dry_run: bool = False,
        yes: bool = False,
        config_path: str | None = None,
        target_type: str | None = None,
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
        self.target_type = target_type
        self.filesystem_root = Path(filesystem_root) if filesystem_root is not None else None
        self.runner = runner or CommandRunner()
        self.ui = ui or UI(no_color=no_color)
        self.backup_manager = BackupManager(backup_dir)
        self.repair_manager = RepairManager()
        self.transaction = RepairTransaction(self.backup_manager, self.repair_manager, lock_dir)
        self.detector = TargetDetector()
        self._last: dict[str, InspectionResult] = {}
        self.aliases = aliases()
        self.supported_services = {item.name: item.engine_spec() for item in iter_services()}
        if self.dry_run:
            self.ui.status("warn", "Dry run enabled. No files or backups will be created.")

    def show_services(self) -> ExitCode:
        self.ui.banner("Supported Services", "Services Lixet can inspect")
        print(
            f"{self.ui.c('Service'.ljust(12), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('Aliases'.ljust(24), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('Default target'.ljust(28), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('Description', self.ui.BOLD + self.ui.CYAN)}"
        )
        for spec in iter_services():
            aliases_text = ", ".join(spec.aliases) or "-"
            print(
                f"{self.ui.c(spec.name.ljust(12), self.ui.BOLD)}  "
                f"{self.ui.clean(aliases_text).ljust(24)}  "
                f"{self.ui.clean(spec.default_path).ljust(28)}  "
                f"{self.ui.clean(spec.description)}"
            )
        return ExitCode.OK

    def scan(self, target: str) -> ExitCode:
        service_name = resolve_service_name(target)
        if service_name in self.supported_services:
            if self.target_type:
                self.ui.status("error", "--type works only with path targets.")
                return ExitCode.USAGE
            return self.scan_service(service_name)

        path = Path(target)
        if not path.exists() and not path.is_symlink():
            self.ui.status("error", f"Target is not a supported service or existing path: {target}")
            self.ui.kv("Supported", ", ".join(service_names()))
            return ExitCode.USAGE
        if self.config_path:
            self.ui.status("error", "--config cannot be combined with a path target.")
            return ExitCode.USAGE
        if self.target_type:
            explicit = resolve_service_name(self.target_type)
            if explicit not in self.supported_services:
                self.ui.status("error", f"Unknown configuration type: {self.target_type}")
                return ExitCode.USAGE
            return self._scan_detected_path(path, explicit, explicit_type=True)

        detected = self.detector.detect(path)
        return self._scan_detection_result(path, detected)

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

    def _scan_detection_result(self, path: Path, detected: DetectionResult) -> ExitCode:
        if detected.status == DetectionStatus.MATCH and detected.best:
            return self._scan_detected_path(path, detected.best.service, detected)
        self._show_detection(detected)
        if detected.status == DetectionStatus.AMBIGUOUS:
            if not self.ui.can_prompt():
                self.ui.status("error", f"Use: lixet scan {self.ui.clean(str(path))} --type <service>")
                return ExitCode.USAGE
            choice = self.ui.prompt("Choose a type number, or q to cancel: ").strip().lower()
            if choice == "q" or not choice:
                self.ui.status("info", "Scan canceled.")
                return ExitCode.USAGE
            try:
                index = int(choice)
                candidate = detected.candidates[index - 1]
            except (ValueError, IndexError):
                self.ui.status("error", "Invalid configuration type selection.")
                return ExitCode.USAGE
            return self._scan_detected_path(path, candidate.service, detected)
        if detected.status == DetectionStatus.ERROR:
            self.ui.status("error", detected.message or "Could not inspect target.")
            return ExitCode.INSPECTION_FAILED
        self.ui.status("error", "Lixet could not identify this configuration file.")
        self.ui.kv("Try", f"lixet scan {self.ui.clean(str(path))} --type nginx")
        return ExitCode.USAGE

    def _scan_detected_path(
        self,
        path: Path,
        service_name: str,
        detected: DetectionResult | None = None,
        explicit_type: bool = False,
    ) -> ExitCode:
        spec = get_service(service_name)
        target_type = "directory" if path.is_dir() else "file"
        if target_type not in spec.accepted_target_types:
            self.ui.status("error", f"{service_name} does not accept a {target_type} target.")
            return ExitCode.USAGE
        self._show_detected(path, service_name, detected, explicit_type)
        return self.scan_service_with_path(service_name, str(path))

    def scan_service_with_path(self, service_name: str, path: str) -> ExitCode:
        old = self.config_path
        self.config_path = path
        try:
            return self.scan_service(service_name)
        finally:
            self.config_path = old

    def run_doctor(self) -> ExitCode:
        while True:
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
            result = self._offer_repairs(items, doctor=True)
            if result == ExitCode.OK:
                continue
            return result

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

        self._selection_help()
        choice = self.ui.prompt("Choose issues: ")
        selection = parse_selection(choice, len(items))
        if selection.action in {SelectionAction.EMPTY, SelectionAction.QUIT}:
            self.ui.status("info", "Repair aborted by user.")
            return ExitCode.ISSUES
        if selection.action == SelectionAction.RESCAN:
            if doctor:
                return ExitCode.OK
            self.ui.status("info", "Rescan is available from doctor sessions.")
            return ExitCode.ISSUES
        if selection.action == SelectionAction.INVALID:
            self.ui.status("error", selection.error)
            return ExitCode.USAGE
        if selection.action == SelectionAction.ALL:
            selected = [(service, item) for service, item in repairable if item.get("repair_level") == "safe"]
            guarded = len([item for _service, item in repairable if item.get("repair_level") == "guarded"])
            if guarded:
                self.ui.status("info", f"Skipped {guarded} guarded repair(s); explicit selection and APPLY are required.")
        else:
            selected = []
            for index in selection.indexes:
                service, item = items[index - 1]
                if not self._is_repairable(item):
                    self.ui.status("info", f"Skipped report-only issue: {item['code']}")
                    continue
                selected.append((service, item))
        if not selected:
            self.ui.status("info", "No selected issue has an automatic repair.")
            return ExitCode.ISSUES
        approved = self._authorize(selected)
        if not approved:
            return ExitCode.ISSUES
        result = self._execute_repairs(approved)
        if doctor and result in {ExitCode.OK, ExitCode.ISSUES}:
            return ExitCode.OK
        return result

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
                self._show_plan_diff(plan)
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
                self._show_plan_diff(plan)
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

    def show_backups(self) -> ExitCode:
        self.ui.banner("Lixet Backups")
        try:
            items = self.backup_manager.list_backups()
        except BackupError as exc:
            self.ui.status("error", str(exc))
            return ExitCode.INSPECTION_FAILED
        valid = [item for item in items if item.metadata]
        corrupt = [item for item in items if item.error]
        if not items:
            self.ui.status("info", "No backups found.")
            return ExitCode.OK
        print(
            f"{self.ui.c('ID'.ljust(34), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('Service'.ljust(12), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('Created'.ljust(19), self.ui.BOLD + self.ui.CYAN)}  "
            f"{self.ui.c('File', self.ui.BOLD + self.ui.CYAN)}"
        )
        for item in valid:
            meta = item.metadata or {}
            created = self._friendly_time(str(meta.get("timestamp") or ""))
            state = str(meta.get("verification") or "")
            suffix = f" [{state}]" if state else ""
            print(
                f"{self.ui.clean(item.backup_id).ljust(34)}  "
                f"{self.ui.clean(str(meta.get('service') or '-')).ljust(12)}  "
                f"{self.ui.clean(created).ljust(19)}  "
                f"{self.ui.clean(str(meta.get('original_path') or '-'))}{self.ui.c(suffix, self.ui.DIM)}"
            )
        for item in corrupt:
            self.ui.status("warn", f"Skipped corrupt backup {item.backup_id}: {item.error}")
        self.ui.status("info", f"{len(valid)} backup(s) found.")
        return ExitCode.OK

    def restore_backup(self, backup_id: str) -> ExitCode:
        try:
            self.backup_manager.validate_backup_id(backup_id)
            meta = self.backup_manager.load_public_metadata(backup_id)
            backup_content = self.backup_manager.read_backup_content(backup_id)
        except BackupError as exc:
            self.ui.status("error", str(exc))
            return ExitCode.REPAIR_FAILED
        target = Path(str(meta["original_path"]))
        self.ui.banner("Lixet Restore")
        self.ui.kv("Backup ID", backup_id)
        self.ui.kv("Service", str(meta.get("service") or "-"))
        self.ui.kv("Target", str(target))
        try:
            current = Path(str(meta.get("resolved_path") or target)).read_bytes() if target.exists() or target.is_symlink() else b""
        except OSError as exc:
            self.ui.status("error", f"Cannot read current target: {exc}")
            return ExitCode.REPAIR_FAILED
        self.ui.section("Restore Diff")
        print(render_diff([DiffFile(str(target), current, backup_content)], self.ui))
        if self.dry_run:
            self.ui.status("warn", "Dry-run complete. No backup was created and no file was restored.")
            return ExitCode.ISSUES
        if not self.ui.can_prompt():
            self.ui.status("error", "Restore requires an interactive terminal. Use --dry-run to preview.")
            return ExitCode.REPAIR_FAILED
        confirm = self.ui.prompt("Type RESTORE to continue: ").strip()
        if confirm != "RESTORE":
            self.ui.status("info", "Restore canceled.")
            return ExitCode.ISSUES
        pre_restore: str | None = None
        try:
            if target.exists() or target.is_symlink():
                pre_restore = self.backup_manager.create_backup(
                    str(target),
                    service=str(meta.get("service") or "restore"),
                    repair_ids=[f"pre-restore:{backup_id}"],
                )
            self.backup_manager.restore_backup(backup_id)
        except BackupError as exc:
            self.ui.status("error", f"Restore failed: {exc}")
            if pre_restore:
                self.ui.kv("Pre-restore backup", Path(pre_restore).parent.name)
            return ExitCode.REPAIR_FAILED
        self.ui.status("ok", "Backup restored successfully.")
        if pre_restore:
            self.ui.kv("Pre-restore backup", Path(pre_restore).parent.name)
        return ExitCode.OK

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

    def _show_plan_diff(self, plan: RepairPlan) -> None:
        self.ui.section("Planned Changes")
        self.ui.kv("File", plan.path)
        if plan.snapshot.is_symlink:
            self.ui.kv("Resolved", plan.snapshot.resolved_path)
        require_unchanged(plan.snapshot)
        before = Path(plan.snapshot.resolved_path).read_bytes()
        after = repaired_bytes(before, plan.fixes)
        print(render_diff([DiffFile(plan.path, before, after)], self.ui))

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
        key = {
            "ssh": "config_test",
            "nginx": "config_test",
            "sudoers": "config_test",
            "fstab": "findmnt_verify",
            "systemd": "config_test",
            "fail2ban": "config_test",
        }.get(service)
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

    def _show_detected(
        self,
        path: Path,
        service: str,
        detected: DetectionResult | None,
        explicit_type: bool,
    ) -> None:
        self.ui.banner("Configuration Detected")
        self.ui.kv("File", str(path))
        print(f"  {self.ui.c('Type:'.ljust(12), self.ui.BOLD + self.ui.CYAN)} {self.ui.c(service, self.ui.BOLD + self.ui.GREEN)}")
        if explicit_type:
            self.ui.kv("Matched by", "explicit --type")
        elif detected and detected.best:
            self.ui.kv("Matched by", self._candidate_reason(detected.best))

    def _show_detection(self, detected: DetectionResult) -> None:
        if detected.status == DetectionStatus.AMBIGUOUS:
            self.ui.status("warn", "Could not identify the configuration type with certainty.")
            for index, candidate in enumerate(detected.candidates, start=1):
                print(
                    f"  {self.ui.c(str(index) + '.', self.ui.BOLD)} "
                    f"{self.ui.c(candidate.service.ljust(10), self.ui.BOLD + self.ui.CYAN)} "
                    f"matched: {self.ui.clean(self._candidate_reason(candidate))}"
                )
            return
        if detected.message:
            self.ui.status("warn", detected.message)

    @staticmethod
    def _candidate_reason(candidate) -> str:
        names = []
        for evidence in candidate.evidence:
            label = {
                "exact_path": "known path",
                "filename": "known filename",
                "parent": "parent directory",
                "content": evidence.detail,
            }.get(evidence.kind, evidence.kind)
            if label not in names:
                names.append(label)
        return ", ".join(names)

    def _selection_help(self) -> None:
        self.ui.section("Choose issues")
        self.ui.kv("number/list/range", "Select repairable issues")
        self.ui.kv("a", "Select all safe repairs")
        self.ui.kv("r", "Rescan")
        self.ui.kv("q", "Quit")

    @staticmethod
    def _friendly_time(value: str) -> str:
        return value.replace("T", " ").replace("+00:00", "").replace("Z", "")[:19] if value else "-"

    def _service_name(self, name: str) -> str:
        return resolve_service_name(name)

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

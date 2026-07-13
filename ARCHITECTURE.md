# Lixet Architecture

Lixet separates inspection, diagnosis, authorization, mutation, and verification. Validators never write files, and a finding is not repairable unless it contains exact snapshot-bound repair actions.

## Repository Layout

```text
backup/       Protected backup bundles and restore verification
cli/          Argument parsing and command dispatch
core/         Engine, registry, detector, typed models, versioning, installer, and updater
repair/       Snapshots, exact text edits, locking, and transactions
services/     File discovery and trusted local command inspection
utils/        Command runner, terminal UI, diff, and selection helpers
validators/   Deterministic issue rules
tests/        Isolated fixtures, regressions, and failure injection
install.py    Shared Python install and uninstall entry point
install.sh    Minimal Linux install wrapper
uninstall.sh  Minimal Linux uninstall wrapper
main.py       CLI entry point
VERSION       Canonical SemVer version
```

Runtime code uses the Python standard library. Ruff, mypy, pytest, coverage, and ShellCheck are optional development tools.

## Scan Flow

For `lixet scan <service>`:

1. `cli/parser.py` validates the command. A custom path is accepted only by `scan`.
2. `core/engine.py` resolves a service, alias, explicit `--type`, or existing path target.
3. Path targets are inspected by `core/detector.py` unless `--type` is explicit. Clear matches proceed, ambiguous interactive matches ask the user, and non-interactive ambiguity is a usage error.
4. The engine builds an inspector with an injectable filesystem root and command runner.
5. A class under `services/` discovers exact files, captures snapshots, and runs bounded local inspection commands when available.
6. A class under `validators/` returns typed issue-shaped dictionaries with deterministic IDs, evidence, severity, and optional exact fixes.
7. The engine displays the check status and findings. It does not call repair code when no repair is available.
8. Dry-run previews the exact unified diff without creating a backup or writing.
9. Interactive use can select one finding, lists, ranges, or all safe findings. `-y` selects safe repairs only; guarded repairs require typing `APPLY`.
10. `RepairTransaction` groups actions by path, rejects cross-service writes to one file, acquires process/thread locks, verifies snapshots, and creates every backup before the first write.
11. `RepairManager` applies exact line operations to the resolved regular target using a temporary file on the same filesystem, `fsync`, and atomic replacement. A supported symlink remains a symlink.
12. The engine re-inspects the service, confirms repaired findings disappeared, rejects new equal-or-higher-severity findings, and runs a required external verifier where applicable.
13. Any failure or interruption rolls the complete repair group back in reverse order. Rollback failure has its own exit code and is never hidden.
14. The engine performs a final service rescan before returning.

`lixet doctor` runs the same inspection path for every registered service without sharing a custom configuration path. It reports each service as checked, not installed, configuration absent, configuration missing, unsupported, or failed. A required skipped or failed check cannot result in a healthy exit. Interactive doctor uses `utils/selection.py` for numbers, lists, ranges, all-safe selection, rescan, quit, and EOF-safe aborts.

## Service Registry And Detection Foundation

The registry in `core/registry.py` is the source of truth for `scan`, `doctor`, `services`, and future path detection. Each entry contains:

- inspector and validator classes;
- default configuration path;
- a discovery command;
- whether the file is system-critical;
- whether absence is a valid configuration state;
- accepted target types;
- known paths, filename patterns, parent-directory patterns, and bounded content signatures;
- the description shown by `lixet services`.

Aliases are resolved before lookup. Runtime systemd inspection still runs when `/etc/systemd/system` has no local units.

`core/detector.py` is the read-only path detection layer for direct file and directory scans. It uses registry metadata, bounded prefix reads, path evidence, filename evidence, parent-directory evidence, and weak content signatures. Content-only matches are never treated as an automatic selection; ambiguous results keep all realistic candidates.

`utils/diff.py` builds unified diffs in memory using the same repair transformation logic as `RepairManager`. It does not write files or create backups. It is used by repair dry-runs, repair confirmations, and restore previews.

## Issue And Repair Models

`core/models.py` defines:

- `ExitCode` for the stable process result contract;
- `RepairLevel` for `safe`, `guarded`, and report-only (`unsafe`) findings;
- `VerificationState` for verified, internally verified, unavailable external verification, failed verification, and rollback failure;
- typed repair actions and issues;
- `VerificationResult`.

Issue IDs include stable issue identity data and are not only repeated rule codes. Repair actions include expected original line or end-of-file content. Supported actions are:

- `append`
- `append_token`
- `replace`
- `replace_preserve_comment`
- `delete`
- `comment_out`
- `comment_out_with_reason`
- `insert_before`
- `insert_after`

The manager rejects unsupported actions, missing preconditions, conflicting edits, changed lines, changed file endings, invalid UTF-8, and out-of-range locations.

## Snapshot And Symlink Model

`repair/snapshot.py` records the original and resolved paths, link target, device, inode, size, timestamps, SHA-256 content hash, mode, uid, and gid. Snapshot capture rejects missing, broken, cyclic, non-regular, unreadable, or changing targets.

When a static symlink is intentionally followed, output includes both link and resolved target. Repair replaces only the resolved regular file atomically and verifies that the original link object still exists. Managed resolver links are identified by `DNSService` and remain report-only.

Current metadata preservation covers mode, uid, gid, and timestamps where the operating system permits it. Explicit SELinux label, ACL, and extended-attribute preservation is a known limitation.

## Backups And Transactions

`BackupManager` stores bundles under `/var/lib/lixet/backups` by default. Tests inject a temporary directory.

Each collision-resistant bundle contains:

- `content`, mode `0600` on POSIX;
- `manifest.json`, mode `0600` on POSIX;
- an ID and timestamp;
- original, resolved, and symlink paths;
- SHA-256, ownership, mode, and timestamps;
- service and repair IDs;
- verification state.

The backup root uses mode `0700` on POSIX. Manifest loading validates identifiers and resolved containment, and restore verifies the content hash and restored state. Backups are outside configuration include directories and are not silently removed after a repair.

Multi-file transactions back up all targets before writing any target. They roll back on normal exceptions, `KeyboardInterrupt`, and `SystemExit`. Cancellation is re-raised after rollback.

`lixet backups` lists public sanitized metadata newest first and skips corrupt bundles with a warning. `lixet restore <backup-id>` validates the ID, validates content hash, shows a unified diff from current content to backup content, requires typing `RESTORE`, creates a pre-restore backup of an existing target, and then restores through the existing verified restore path. Dry-run restore creates no backup and writes nothing.

## Trusted Commands

`utils/command.py` does not search the inherited `PATH`. It resolves commands only inside approved system directories, validates executable and parent ownership/permissions on POSIX, uses `shell=False`, supplies a controlled environment with `LC_ALL=C`, sets strict timeouts, and bounds captured output.

Unavailable commands are represented as unavailable checks. They are not treated as successful verifiers.

Authoritative tools currently include:

- `sshd -t` and effective `sshd -T` inspection;
- `nginx -t` against the root configuration;
- `visudo -cf`;
- `findmnt --verify --tab-file`;
- `systemd-analyze verify`.

Other commands such as `ufw`, `ip`, `systemctl`, and `resolvectl` provide read-only runtime evidence.

## Validator Policy

- **SSH:** follows includes with cycle, depth, and file bounds; applies first-obtained-value semantics; treats hardening as policy; never auto-disables root or password access. Only one exact `sshd`-rejected directive may become guarded.
- **Nginx:** follows exact includes with bounds; handwritten brace and semicolon checks are quote/comment aware and report-only; `nginx -t` is authoritative.
- **DNS:** detects managed resolver setups and containers; performs no external lookup; never inserts a universal fallback resolver.
- **Networking:** validates address fields and runtime permission errors separately. Only standard localhost recovery is safe.
- **UFW:** reads state and defaults from their proper files, respects last-assignment semantics, and keeps policy/startup changes report-only. It executes no firewall-changing command.
- **systemd:** inspects runtime failures independently of local units, reads drop-ins, accepts optional `[Unit]` and valid oneshot forms, and keeps behavior changes report-only.
- **Fail2ban:** reads Fail2ban roots and files, follows bounded `[INCLUDES]` `before` and `after` references, checks `fail2ban-client -t` and `status` when available, reports static syntax problems, missing includes, cycles, missing enabled filters, and runtime failures. It never restarts Fail2ban, changes firewall rules, rewrites actions, or changes ban policy. Exact verifier-rejected override lines may become guarded only when they are not packaged defaults.
- **sudoers:** trusts `visudo`; the main file is never automatically repaired. One exact included-file syntax line may become guarded.
- **fstab:** uses `findmnt`, parses escaped whitespace, and never runs `mount -a`. Findings are report-only.
- **sysctl:** models directory/file precedence and `/etc/sysctl.conf`, reports complete override evidence, and never changes or applies kernel policy automatically.

## Installer And Updater

`InstallTransaction` is shared by `install.py` and the updater. It validates exact required file types, writes an ownership marker, stages into a unique directory, preserves the previous installation and command entry, and restores both after failures. It removes only staging and backup paths created by its transaction.

The updater selects a newer published GitHub Release from the installed stable or prerelease channel. It has no branch fallback. It downloads GitHub's automatic `zipball_url` source archive, extracts it into a temporary directory, validates paths and file types, checks that `VERSION` matches the release tag after SemVer normalization, then runs compile and CLI smoke checks before the install transaction begins. Downloads and extraction are bounded; path traversal, duplicate paths, symlinks, special files, oversized content, mismatched versions, same-version reinstalls, and downgrades are rejected.

## Non-Goals

Lixet does not automatically restart services, alter firewall rules, mount filesystems, apply sysctl settings, choose DNS providers, or decide an administrator's SSH/authentication policy. Those operations require system context that the current deterministic safety model cannot prove.

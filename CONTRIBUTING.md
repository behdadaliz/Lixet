# Contributing To Lixet

Lixet may inspect and modify security-sensitive Linux configuration. A contribution should be deterministic, conservative, and testable without touching the developer's real system.

## Ground Rules

- Do not add AI-generated diagnosis or repair behavior.
- Prefer the Python standard library for runtime code.
- Never use the inherited `PATH` for system inspection commands.
- Validators diagnose; they do not write files or run policy-changing commands.
- Prefer false negatives over noisy false positives. Low-confidence guesses should not be visible problems.
- Do not restart services, alter firewall rules, mount filesystems, or apply sysctl values.
- Do not restart Fail2ban, alter Fail2ban firewall actions, or choose ban policy for the administrator.
- Do not weaken snapshot, backup, transaction, verification, or updater checks to make a feature easier.
- Preserve unrelated user changes and keep pull requests focused.

## Local Setup

Use Python 3.10 or newer. Development dependencies are optional and are not installed by Lixet at runtime.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows, activate with `.venv\Scripts\activate`. Runtime behavior remains Linux-only; Windows is useful for isolated unit tests.

Run the local quality checks:

```bash
python -m compileall -q backup cli core repair services utils validators install.py main.py
python -m pytest
python -m coverage run -m pytest
python -m coverage report
python -m ruff format --check .
python -m ruff check .
python -m mypy
shellcheck install.sh uninstall.sh
```

ShellCheck and Linux symlink behavior should also be checked on a Linux system. No test may read or modify the host's real `/etc`, `/opt`, `/var/lib/lixet`, or `/usr/local/bin` paths.

## Adding Or Changing A Service

1. Put file discovery and read-only command inspection under `services/`.
2. Make filesystem roots and external commands injectable.
3. Put deterministic diagnosis under `validators/`.
4. Return the shared issue shape and include evidence and source commands when available.
5. Register metadata in `core/registry.py` so `scan`, `doctor`, `services`, and path detection stay consistent.
6. Add deterministic path, filename, parent-directory, and bounded content signatures only when they are specific enough to avoid false positives.
7. Add realistic temporary fixtures, failure cases, and distribution-specific cases when semantics differ.
8. Update documentation only after behavior and tests are stable.

Use official upstream documentation as the source of truth for OpenSSH, Nginx, systemd, sudo/visudo, util-linux/findmnt, procps/sysctl, UFW, and resolver semantics.

## Findings And Repair Levels

Every finding includes a unique `id`, stable `code`, severity, service, location, evidence, safety notes, confidence, repair level, and zero or more exact fixes.

- `safe`: deterministic and narrowly scoped, with focused regression coverage. It may be approved by `-y`.
- `guarded`: sensitive, exact, reversible, and externally verifiable. It requires typing `APPLY` interactively.
- `unsafe`: report-only. Despite the internal enum value, this means Lixet refuses to perform the change automatically.

Do not label a repair safe because it is common. Prove that:

- the broken state and desired state are unambiguous;
- expected original content binds every edit to the inspection snapshot;
- unrelated formatting, comments, aliases, and line endings survive;
- backup and rollback cover interruption and verification failure;
- post-repair inspection removes the finding without introducing an equal-or-higher-severity issue;
- a required authoritative verifier is available and passes.

The main sudoers file, firewall policy, DNS provider choice, mount behavior, sysctl policy, SSH authentication policy, and service behavior should remain report-only unless a future design proves stronger guarantees. Normal state such as inactive UFW, managed DNS, valid sysctl layering, and unused stock configuration libraries should not be reported as broken.

## Tests

Use `TemporaryDirectory`, injected roots, fake command runners, fake release responses, and mocked installers. Mandatory safety tests cannot be skipped.

Tests should cover healthy, broken, unavailable-tool, permission, concurrent-edit, interruption, rollback, and malicious-input paths. A repair test should assert both the intended change and preservation of unrelated bytes or metadata.

Diff-related changes must test plain output, colored output, no-color output, redirected/non-TTY behavior, line-ending preservation, and zero-write dry-runs.

Backup restore changes must test dry-run, cancel, exact `RESTORE` confirmation, pre-restore backup creation, hash mismatch, invalid IDs, traversal attempts, and symlink behavior when the platform supports it.

Fail2ban changes must avoid a generic strict INI parser. Test real Fail2ban-style includes, `.local` overrides, jail.d/filter.d/action.d paths, command-unavailable paths, authoritative `fail2ban-client -t` success/failure, and report-only behavior. Clean stock filter files must not create duplicate-option floods. Never add a Fail2ban safe repair without a separate safety design.

Doctor logging changes must test redaction, no ANSI output, fallback directories, retention, and backup preservation. Uninstall changes must test dry-run, cancellation, explicit `UNINSTALL`, idempotency, unowned-target refusal, and preservation of `/var/lib/lixet/backups`.

When a platform cannot create real symlinks locally, keep a non-skipped simulation and verify the real symlink path on Linux. Do not mark the platform-independent safety test as skipped.

Coverage must remain at or above the configured threshold. Raising raw coverage is not a substitute for meaningful failure-injection tests.

## Installer And Release Changes

Installer, updater, and uninstaller changes require phase failure injection. Never test them against real install paths.

The updater uses GitHub's automatic source archive for the selected published Release. Maintainers do not need to upload custom release files. The release tag and canonical `VERSION` content must agree under SemVer normalization. Do not add mutable branch fallback or silent downgrade behavior.

Release flow:

1. Update `VERSION`.
2. Commit and push the release code.
3. Create a GitHub tag such as `v0.3.0-beta`.
4. Create and publish a GitHub Release from that tag.

Do not bump `VERSION` repeatedly. Update it once after the full quality gate passes, then update `README.md`, `ARCHITECTURE.md`, and `CONTRIBUTING.md` if the behavior changed. Publishing a GitHub release is a separate maintainer action.

## Pull Requests

A pull request should state:

- the problem and affected safety property;
- the source documentation used for configuration semantics;
- tests that failed before and pass after the change;
- whether files, privileges, network access, or trusted commands are involved;
- documentation and compatibility impact;
- remaining limitations.

Use the pull request template and remove secrets, private keys, tokens, hostnames, private addresses, and sensitive configuration from all examples and logs.

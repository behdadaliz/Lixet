# Contributing To Lixet

Lixet may inspect and modify security-sensitive Linux configuration. A contribution should be deterministic, conservative, and testable without touching the developer's real system.

## Ground Rules

- Do not add AI-generated diagnosis or repair behavior.
- Prefer the Python standard library for runtime code.
- Never use the inherited `PATH` for system inspection commands.
- Validators diagnose; they do not write files or run policy-changing commands.
- Keep uncertain findings report-only.
- Do not restart services, alter firewall rules, mount filesystems, or apply sysctl values.
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

ShellCheck and Linux symlink behavior should also pass in GitHub Actions. No test may read or modify the host's real `/etc`, `/opt`, `/var/lib/lixet`, or `/usr/local/bin` paths.

## Adding Or Changing A Service

1. Put file discovery and read-only command inspection under `services/`.
2. Make filesystem roots and external commands injectable.
3. Put deterministic diagnosis under `validators/`.
4. Return the shared issue shape and include evidence and source commands when available.
5. Register metadata in `core/engine.py` so `scan`, `doctor`, and `services` stay consistent.
6. Add realistic temporary fixtures, failure cases, and distribution-specific cases when semantics differ.
7. Update documentation only after behavior and tests are stable.

Use official upstream documentation as the source of truth for OpenSSH, Nginx, systemd, sudo/visudo, util-linux/findmnt, procps/sysctl, UFW, and resolver semantics.

## Findings And Repair Levels

Every finding includes a unique `id`, stable `code`, severity, service, location, evidence, safety notes, repair level, and zero or more exact fixes.

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

The main sudoers file, firewall policy, DNS provider choice, mount behavior, sysctl policy, SSH authentication policy, and service behavior should remain report-only unless a future design proves stronger guarantees.

## Tests

Use `TemporaryDirectory`, injected roots, fake command runners, fake release responses, and mocked installers. Mandatory safety tests cannot be skipped.

Tests should cover healthy, broken, unavailable-tool, permission, concurrent-edit, interruption, rollback, and malicious-input paths. A repair test should assert both the intended change and preservation of unrelated bytes or metadata.

When a platform cannot create real symlinks locally, keep a non-skipped simulation and rely on the Linux CI job for the real symlink path. Do not mark the platform-independent safety test as skipped.

Coverage must remain at or above the configured threshold. Raising raw coverage is not a substitute for meaningful failure-injection tests.

## Installer And Release Changes

Installer and updater changes require phase failure injection. Never test them against real install paths.

The updater uses GitHub's automatic source archive for the selected published Release. Maintainers do not need to upload custom release files. The release tag and canonical `VERSION` content must agree under SemVer normalization. Do not add mutable branch fallback or silent downgrade behavior.

Release flow:

1. Update `VERSION`.
2. Commit and push the release code.
3. Create a GitHub tag such as `v0.2.3-beta`.
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
